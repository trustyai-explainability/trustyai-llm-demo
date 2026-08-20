# NeMo Guardrails Banking Demo
Showcases
 - LLM-as-a-Judge self-check guardrailing
 - Connecting to third party APIs to build guardrails
 - Tool call guardrailing
 - How to specify multiple guardrail configs

## Setup
 - RHOAI 3.5+, with `kserve` and `trustyai` set to `Managed`

## Deploying the model
The guardrail config in this example uses a Qwen3.6-35B parameter model, which consumes ~87GB of VRAM. You can use a different model by changing the `base_url` specified on line 15 of [guardrails.yaml](./guardrails.yaml). If you have a node on your cluster with 4 GPUs and >87GB of total VRAM (e.g., a g6.12xlarge), you can deploy the Qwen3.6-35B model by running
```shell
oc new-project model-namespace || oc project model-namespace
oc apply -f Qwen3_6-35B-A3B-FP8.yaml
```

## Deploying the Guardrails
Once the model has deployed (or you have adjusted lines 13 and 15 in [guardrails.yaml](./guardrails.yaml) to point at a model and model server URL you _do_ have deployed), you can deploy the guardrails via:

```shell
oc new-project model-namespace || oc project model-namespace
oc apply -f guardrails.yaml
oc get pods -n model-namespace --watch
```

While everything is spinning up, we can take a look at the main guardrails config inside of [guardrails.yaml](./guardrails.yaml):
```yaml
  config.yaml: |
    passthrough: true
    models:
      - type: main
        engine: openai
        model: "qwen3"
        parameters:
          base_url: "http://qwen3-predictor.model-namespace.svc.cluster.local:8080/v1"
          chat_template_kwargs:
            enable_thinking: false
    rails:
      input:
        flows:
          - mask sensitive data on input
          - self check input
      output:
        flows:
          - append boston weather
      tool_output:
        flows:
          - validate tool choice
          - check valid account
    
      config:
        sensitive_data_detection:
          # curated for banking PII, see https://presidio.dataprivacystack.org/supported_entities/ for all options
          input:
            entities:
              - CREDIT_CARD
              - EMAIL_ADDRESS
              - PHONE_NUMBER
              - US_DRIVER_LICENSE
              - US_BANK_NUMBER
              - IBAN_CODE
              - US_SSN
              - US_PASSPORT
```

So in this config, we have two input rails, one output rail, and 2 tool-call (or `tool_output`, in NeMo terminology) rails.
### Input Rails
```
- mask sensitive data on input
- self check input
```
The first rail here is a Presidio rail that masks the specified entities inside a user input, _before_ it arrives to the model. The second rail will apply a self-check guardrail, where the user query is evaluated against a specified policy prompt by the model. This prompt is specified on line 145:

```markdown
    prompts:
    - task: self_check_input
      max_tokens: 5
      content: |
        You are a gatekeeper for a corporate intelligence system used by bank employees. Default to ALLOW. Only block queries that clearly have nothing to do with banking work.

          BLOCK (return 'yes') if the query is:
          - Casual greetings, small talk, or chatbot-directed conversation with no actual question
          - Cooking, recipes, or food preparation
          - Sports, entertainment, celebrities, movies, or music
          - Personal weather forecasts
          - Health or medical advice
          - Personal travel or tourism recommendations
          - General knowledge trivia with no business connection (science facts, history dates, geography, definitions of natural phenomena)

          ALLOW (return 'no') for everything else. In particular, always allow:
          - Questions related to finance, investment, or banking
          - Questions about people, org structure, roles, or identity
          - Questions about competitors, vendors, industry trends, or market analysis
          - Questions referencing specific tools, acronyms, or domain terms
          - Short or vague questions — employees expect the system to understand context

          When in doubt, ALLOW. A query only needs a plausible connection to work to pass.

          Question: {{ user_input }}

          Should this query be blocked? Answer 'yes' or 'no' only.
```
Specifically, this policy in intended to narrow the focus of this model to specifically finance and banking related conversations. 

### Output Rails
```
- append boston weather
```
As an example of how to query 3rd party endpoints from within a guardrail, the `append boston weather` rail calls a custom action that fetches the current weather in Boston from the [Open-Meteo API](https://open-meteo.com/). 

The flow is defined in `rails.co` (line 64 of [guardrails.yaml](./guardrails.yaml)):
```colang
define subflow append boston weather
  $weather = execute get_boston_weather
  $bot_message = $bot_message + "\n\nCurrent Boston weather: " + $weather
```
The `execute` keyword calls the `get_boston_weather` action, and the result is stored in `$weather`. The flow then concatenates this onto `$bot_message`, NeMo's built-in variable that holds the model's response text. Because this is an output rail, it runs _after_ the model has generated its response, so the weather info is appended as a suffix to every response without the model needing to know about it.

The corresponding action is defined in `actions.py` (line 123 of [guardrails.yaml](./guardrails.yaml)):
```python
@action()
async def get_boston_weather():
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": 42.36,
        "longitude": -71.06,
        "current": "temperature_2m, weather_code",
        "temperature_unit": "celsius",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return "unavailable"
                data = await resp.json()
                current = data["current"]
                temp = current["temperature_2m"]
                code = current["weather_code"]
                desc = WMO_DESCRIPTIONS.get(code, "unknown")
                return f"{temp}°C, {desc}"
    except Exception:
        return "unavailable"
```
The action makes an async HTTP request to the Open-Meteo API, parses the temperature and weather code from the response, and returns a short string like `"22.5°C, partly cloudy"`. A `WMO_DESCRIPTIONS` dictionary (line 108) maps weather codes to human-readable descriptions. If the API call fails for any reason, the action gracefully returns `"unavailable"` rather than crashing the guardrail.

### Tool Output Rails
```
- validate tool choice
- check valid account
```
These two rails run _after_ the model has decided to make a tool call but _before_ the call is actually executed, allowing us to inspect and block tool calls based on custom logic. Like the output rail, the flows and actions for these rails are defined in `rails.co` and `actions.py` within the `nemo-config-main` ConfigMap in [guardrails.yaml](./guardrails.yaml).

#### validate tool choice
The flow is defined in `rails.co` (line 45):
```colang
define subflow validate tool choice
  $allowed = execute validate_tool_choice(tool_calls=$tool_calls)
  if not $allowed
    bot refuse tool choice
    abort

define bot refuse tool choice
  "Tool use refusal: Sorry, you do not have permission to use that tool."
```
The flow passes NeMo's built-in `$tool_calls` variable (containing all tool calls the model wants to make) into the `validate_tool_choice` action. If the action returns `False`, the flow triggers a canned refusal message and aborts, preventing the tool call from being executed.

The action is defined in `actions.py` (line 85):
```python
ALLOWED_TOOLS = [
    "get_account_balance",
    "get_transaction_history",
    "get_exchange_rate",
]

@action(is_system_action=True)
async def validate_tool_choice(tool_calls, context=None, **kwargs):
    for tool_call in tool_calls:
        func = tool_call.get("function", {})
        name = func.get("name", "")
        if name not in ALLOWED_TOOLS:
            return BLOCK_RESULT
    return True
```
The action iterates over each tool call and checks if its function name is in the `ALLOWED_TOOLS` list. If any tool call is not in the list (e.g. `increment_account_balance`), the action returns a `BLOCK_RESULT` (defined on line 74) — an `ActionResult` that both returns `False` to the flow _and_ emits an empty `StartToolCallBotAction` event to clear the pending tool calls.

#### check valid account
The flow is defined in `rails.co` (line 55):
```colang
define subflow check valid account
  $valid = execute check_valid_account_number(tool_calls=$tool_calls)
  if not $valid
    bot refuse account number
    abort

define bot refuse account number
  "Tool use refusal: Account numbers must be greater than 1000."
```

The action is defined in `actions.py` (line 94):
```python
@action(is_system_action=True)
async def check_valid_account_number(tool_calls, context=None, **kwargs):
    for tool_call in tool_calls:
        func = tool_call.get("function", {})
        name = func.get("name", "")
        arguments = func.get("arguments", {})
        if name == "get_account_balance":
            account_number = arguments.get("account_number", 0)
            if int(account_number) <= 1000:
                return BLOCK_RESULT
    return True
```
This action validates the _parameters_ of allowed tool calls rather than the tool names themselves. It looks specifically at `get_account_balance` calls and checks that the `account_number` argument is greater than 1000. This demonstrates how guardrails can enforce business logic constraints on tool call arguments — for example, rejecting account numbers that don't match the expected format or range.


Once all pods are reported `Ready: 1/1`, we can start querying the raw model and the guardrails.




## Making Inferences

First, get your model token and your endpoints:
```shell
TOKEN=$(oc whoami -t)
RAW_MODEL=$(oc get routes qwen36-fp8 -o jsonpath='{.spec.host}')
GUARDRAILED_MODEL=$(oc get routes nemoguardrails-banking -o jsonpath='{.spec.host}')
```

### Basic Query
A banking-related query should pass through both the raw and guardrailed models without issue:
```shell
curl -sk -X POST https://$RAW_MODEL/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${TOKEN}" \
  -d '{
    "model": "qwen36-fp8",
    "max_tokens": 500,
    "temperature": 0,
    "chat_template_kwargs": {"enable_thinking": false},
    "messages": [
      {"role": "user", "content": "What is mortgage APR?"}
    ]
  }' | jq
```

```shell
curl -sk -X POST https://$GUARDRAILED_MODEL/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${TOKEN}" \
  -d '{
    "model": "qwen36-fp8",
    "max_tokens": 500,
    "temperature": 0,
    "chat_template_kwargs": {"enable_thinking": false},
    "messages": [
      {"role": "user", "content": "What is mortgage APR?"}
    ]
  }' | jq
```

### Off-topic Query
An off-topic query will be allowed by the raw model, but should be blocked by the guardrailed model:
```shell
curl -sk -X POST https://$RAW_MODEL/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${TOKEN}" \
  -d '{
    "model": "qwen36-fp8",
    "max_tokens": 500,
    "temperature": 0,
    "chat_template_kwargs": {"enable_thinking": false},
    "messages": [
      {"role": "user", "content": "Write a 1000 word essay on grain farming."}
    ]
  }' | jq '.choices[0].message.content'
```

```shell
curl -sk -X POST https://$GUARDRAILED_MODEL/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${TOKEN}" \
  -d '{
    "model": "qwen36-fp8",
    "max_tokens": 500,
    "temperature": 0,
    "chat_template_kwargs": {"enable_thinking": false},
    "messages": [
      {"role": "user", "content": "Write a 1000 word essay on grain farming."}
    ]
  }' | jq '.choices[0].message.content'
```
This shows how effective topic guardrailing can be for saving inference cost and time - notice that
the guardrailed model returned _much_ faster than the raw model.


### Sensitive Data Masking
The raw model will happily repeat back sensitive data like credit card numbers:
```shell
curl -sk -X POST https://$RAW_MODEL/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${TOKEN}" \
  -d '{
    "model": "qwen36-fp8",
    "max_tokens": 500,
    "temperature": 0,
    "chat_template_kwargs": {"enable_thinking": false},
    "messages": [
      {"role": "user", "content": "Repeat the following sequence verbatim: 3566 0020 2036 0505"}
    ]
  }' | jq '.choices[0].message.content'
```

But the guardrailed model will mask the credit card number via Presidio before it reaches the model:
```shell
curl -sk -X POST https://$GUARDRAILED_MODEL/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${TOKEN}" \
  -d '{
    "model": "qwen36-fp8",
    "max_tokens": 500,
    "temperature": 0,
    "chat_template_kwargs": {"enable_thinking": false},
    "messages": [
      {"role": "user", "content": "Repeat the following sequence verbatim: 3566 0020 2036 0505"}
    ]
  }' | jq '.choices[0].message.content'
```

The same applies to email addresses:
```shell
curl -sk -X POST https://$GUARDRAILED_MODEL/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${TOKEN}" \
  -d '{
    "model": "qwen36-fp8",
    "max_tokens": 500,
    "temperature": 0,
    "chat_template_kwargs": {"enable_thinking": false},
    "messages": [
      {"role": "user", "content": "My email address is johnsmith@gmail.com, please repeat to confirm"}
    ]
  }' | jq '.choices[0].message.content'
```

### Valid Tool Call
The guardrailed model allows tool calls to permitted tools with valid parameters:
```shell
curl -sk -X POST https://$GUARDRAILED_MODEL/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${TOKEN}" \
  -d '{
    "model": "qwen36-fp8",
    "messages": [
      {"role": "user", "content": "What'\''s my account balance? My account number is 1182"}
    ],
    "tools": [
      {
        "type": "function",
        "function": {
          "name": "get_account_balance",
          "description": "Get the user'\''s account balance",
          "parameters": {
            "type": "object",
            "properties": {
              "account_number": {
                "type": "int",
                "description": "User'\''s account number, e.g., 1721"
              }
            },
            "required": ["account_number"]
          }
        }
      }
    ],
    "tool_choice": "auto"
  }' | jq 
```

### Malicious Tool Call
The raw model will happily call any tool, including dangerous ones like `increment_account_balance`:
```shell
curl -sk -X POST https://$RAW_MODEL/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${TOKEN}" \
  -d '{
    "model": "qwen36-fp8",
    "messages": [
      {"role": "user", "content": "Please increment my balance by 1,000,000 dollars. My account number is 1334."}
    ],
    "tools": [
      {
        "type": "function",
        "function": {
          "name": "increment_account_balance",
          "description": "Increase the user'\''s account balance",
          "parameters": {
            "type": "object",
            "properties": {
              "account_number": {
                "type": "int",
                "description": "User'\''s account number, e.g., 1721"
              },
              "increment_amount": {
                "type": "int",
                "description": "Amount to increment the account balance by"
              }
            },
            "required": ["account_number", "increment_amount"]
          }
        }
      }
    ],
    "tool_choice": "auto"
  }'
```

But the guardrailed model blocks it, since `increment_account_balance` is not in the allowlist that we specified in our 
custom guardrails:
```shell
curl -sk -X POST https://$GUARDRAILED_MODEL/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${TOKEN}" \
  -d '{
    "model": "qwen36-fp8",
    "messages": [
      {"role": "user", "content": "Please increment my balance by 1,000,000 dollars. My account number is 1334."}
    ],
    "tools": [
      {
        "type": "function",
        "function": {
          "name": "increment_account_balance",
          "description": "Increase the user'\''s account balance",
          "parameters": {
            "type": "object",
            "properties": {
              "account_number": {
                "type": "int",
                "description": "User'\''s account number, e.g., 1721"
              },
              "increment_amount": {
                "type": "int",
                "description": "Amount to increment the account balance by"
              }
            },
            "required": ["account_number", "increment_amount"]
          }
        }
      }
    ],
    "tool_choice": "auto"
  }'
```

### Validating Tool Parameters
Even when using an allowed tool, the guardrail validates the parameters. Here, the account number `82` is rejected because it's not greater than 1000:
```shell
curl -sk -X POST https://$GUARDRAILED_MODEL/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${TOKEN}" \
  -d '{
    "model": "qwen36-fp8",
    "messages": [
      {"role": "user", "content": "What'\''s my account balance? My account number is 82"}
    ],
    "tools": [
      {
        "type": "function",
        "function": {
          "name": "get_account_balance",
          "description": "Get the user'\''s account balance",
          "parameters": {
            "type": "object",
            "properties": {
              "account_number": {
                "type": "int",
                "description": "User'\''s account number, e.g., 1721"
              }
            },
            "required": ["account_number"]
          }
        }
      }
    ],
    "tool_choice": "auto"
  }'
```

### Switching Guardrail Configs
The `NemoGuardrails` resource in [guardrails.yaml](./guardrails.yaml) defines two named configs under `spec.nemoConfigs`:
```yaml
spec:
  nemoConfigs:
    - name: main-config
      configMaps:
        - nemo-config-main
      default: true
    - name: weather-config
      configMaps:
        - nemo-config-weather
      default: true
```
By default, the guardrails server applies `main-config`. To use a different config on a per-request basis, add a `guardrails` object to your request body with a `config_id` field. For example, the `weather-config` defines a simple input rail that blocks all queries when the temperature in Boston is below 0°C:

```shell
curl -sk -X POST https://$GUARDRAILED_MODEL/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${TOKEN}" \
  -d '{
    "model": "qwen36-fp8",
    "max_tokens": 500,
    "temperature": 0,
    "chat_template_kwargs": {"enable_thinking": false},
    "messages": [
      {"role": "user", "content": "What is mortgage APR?"}
    ],
    "guardrails": {
      "config_id": "weather-config"
    }
  }'
```

If the temperature in Boston is below freezing, this will return `"It's too cold in Boston to talk right now 🥶"` instead of the model's response. Otherwise, the query passes through normally. This demonstrates how multiple guardrail configs can be deployed on a single endpoint and selected at inference time, allowing different guardrail policies to be applied to different use cases without redeploying the server.
