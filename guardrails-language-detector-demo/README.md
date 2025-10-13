# Language Detector Guardrails

In this demo, we will use [papluca/xlm-roberta-base-language-detection](https://huggingface.co/papluca/xlm-roberta-base-language-detection), a sequence classification model trained to detect 20 different lanaguages as a guardrail to block inputs and outputs in languages that are not allowed. 

## Prerequisites

1. Ensure you have the Red Hat Openshift AI operator with the TrustyAI component enabled. 
2. GPU is recommended.
3. A namespace/project is created and you have access to it.

## 1) Apply the service account and role bindings

```
oc apply -f service_account.yaml
```

## 2) Set up the detector model storage container

```
oc apply -f detector_storage.yaml
```

## 3) Deploy detector model

```
oc apply -f detector_deployment.yaml
```

Note that `SAFE_LABELS` environment variable is set to `'[3, "pl"]'` in the `detector_deployment.yaml`. Subsequently, this means that only Polish language should be allowed by the guardrail.

Generally, `SAFE_LABELS` is a list that can contain either string or integer labels (or a mixture of both). The labels should correspond to the labels used by the underlying sequence classification model; these can be usually found in the model card. For example, for the `xlm-roberta-base-language-detection` model used in this demo, the labels can be found [here](https://huggingface.co/papluca/xlm-roberta-base-language-detection/blob/main/config.json) (the mapping is in the `id2label` field).

If `SAFE_LABELS` is not set inside the `detector_deployment.yaml`, then the default behaviour is to set first labels as safe (i.e. `'[0]'`).

## 4) Set up the generative llm model storage container

```
oc apply -f llm_storage.yaml
```

## 5) Deploy the generative llm model

```
oc apply -f llm_deployment.yaml
```

## 6) Deploy the guardrails orchestrator

```
oc apply -f guardrails_auto_config.yaml
```

## Sample requests -- Detector API

Get the route: 

```
DETECTOR_ROUTE=$(oc get routes language-detector-route -o jsonpath='{.spec.host}')
```

### Perform the health check

```
curl -v -H "Authorization: Bearer $(oc whoami -t)" https://$DETECTOR_ROUTE/health | jq
```

this should return:

`"ok"`

### Send requests that should be allowed

These request should be allowed by the guardrail as their language is in the safe list of labels (Polish)

```
curl -v -X POST \
  "https://$DETECTOR_ROUTE/api/v1/text/contents" \
  -H "Authorization: Bearer $(oc whoami -t)" \
  -H 'accept: application/json' \
  -H 'detector-id: language_detector' \
  -H 'Content-Type: application/json' \
  -d '{
    "contents": ["Czesc - czy mozes mi pomoc?", "Jaki AI model jest najlepszy?"],
    "detector_params": {}
  }' | jq
```

this should return:

```
[
  [],
  []
]
```

### Send requests that should be blocked

These requests should be blocked by the guardrail as their language is not in the safe list of labels (Polish)

```
curl -v -X POST \
  "https://$DETECTOR_ROUTE/api/v1/text/contents" \
  -H "Authorization: Bearer $(oc whoami -t)" \
  -H 'accept: application/json' \
  -H 'detector-id: language_detector' \
  -H 'Content-Type: application/json' \
  -d '{
    "contents": [
        "Hello - can you help me?",
        "Which AI model is the best?",
        "Bonjour - pouvez-vous m'"'"'aider?",
        "Quel modèle d'"'"'IA est le meilleur?",
        "Hola - ¿puedes ayudarme?",
        "¿Cuál es el mejor modelo de IA?",
        "Hallo - kannst du mir helfen?",
        "Welches KI-Modell ist das beste?",
        "Ciao - puoi aiutarmi?",
        "Qual è il miglior modello di intelligenza artificiale?"
    ],
    "detector_params": {}
  }' | jq
```

this should return:

```
[
  [
    {
      "start": 0,
      "end": 24,
      "text": "Hello - can you help me?",
      "detection": "single_label_classification",
      "detection_type": "en",
      "score": 0.9464484453201294,
      "evidences": [],
      "metadata": {}
    }
  ],
  [
    {
      "start": 0,
      "end": 27,
      "text": "Which AI model is the best?",
      "detection": "single_label_classification",
      "detection_type": "en",
      "score": 0.9105632901191711,
      "evidences": [],
      "metadata": {}
    }
  ],
  [
    {
      "start": 0,
      "end": 30,
      "text": "Bonjour - pouvez-vous m'aider?",
      "detection": "single_label_classification",
      "detection_type": "fr",
      "score": 0.9945297837257385,
      "evidences": [],
      "metadata": {}
    }
  ],
  [
    {
      "start": 0,
      "end": 33,
      "text": "Quel modèle d'IA est le meilleur?",
      "detection": "single_label_classification",
      "detection_type": "fr",
      "score": 0.9915143251419067,
      "evidences": [],
      "metadata": {}
    }
  ],
  [
    {
      "start": 0,
      "end": 24,
      "text": "Hola - ¿puedes ayudarme?",
      "detection": "single_label_classification",
      "detection_type": "es",
      "score": 0.9750027656555176,
      "evidences": [],
      "metadata": {}
    }
  ],
  [
    {
      "start": 0,
      "end": 31,
      "text": "¿Cuál es el mejor modelo de IA?",
      "detection": "single_label_classification",
      "detection_type": "es",
      "score": 0.9921737909317017,
      "evidences": [],
      "metadata": {}
    }
  ],
  [
    {
      "start": 0,
      "end": 29,
      "text": "Hallo - kannst du mir helfen?",
      "detection": "single_label_classification",
      "detection_type": "de",
      "score": 0.9949387311935425,
      "evidences": [],
      "metadata": {}
    }
  ],
  [
    {
      "start": 0,
      "end": 32,
      "text": "Welches KI-Modell ist das beste?",
      "detection": "single_label_classification",
      "detection_type": "de",
      "score": 0.9937286376953125,
      "evidences": [],
      "metadata": {}
    }
  ],
  [
    {
      "start": 0,
      "end": 21,
      "text": "Ciao - puoi aiutarmi?",
      "detection": "single_label_classification",
      "detection_type": "it",
      "score": 0.9950234889984131,
      "evidences": [],
      "metadata": {}
    }
  ],
  [
    {
      "start": 0,
      "end": 54,
      "text": "Qual è il miglior modello di intelligenza artificiale?",
      "detection": "single_label_classification",
      "detection_type": "it",
      "score": 0.9948535561561584,
      "evidences": [],
      "metadata": {}
    }
  ]
]
```

## Sample requests -- Orchestrator API


1. Get the route of the health service

```
ORCHESTRATOR_HEALTH_ROUTE=$(oc get routes guardrails-orchestrator-health -o jsonpath='{.spec.host}')
```

2. Get the route of the main guardrails orchestrator service

```
ORCHESTRATOR_ROUTE=$(oc get routes guardrails-orchestrator -o jsonpath='{.spec.host}')
```

### Perform the info check

```
curl -v -H "Authorization: Bearer $(oc whoami -t)" https://$ORCHESTRATOR_HEALTH_ROUTE/info | jq
```

this should return:

```
{
  "services": {
    "built-in-detector": {
      "status": "HEALTHY"
    },
    "language-detector": {
      "status": "HEALTHY"
    },
    "openai": {
      "status": "HEALTHY"
    }
  }
}
```

### Send a request to the detector that should be allowed

```
curl -v \
  -H "Authorization: Bearer $(oc whoami -t)" \
  -H "accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{
    "detectors": {
      "language-detector": {}
    },
    "content": "Czesc - czy mozesz mi pomoc?"
  }' \
  "https://$ORCHESTRATOR_ROUTE/api/v2/text/detection/content" | jq
```

which should return:

```
{
  "detections": []
}
```

### Send a request to the detector that should be blocked

```
curl -v \
  -H "Authorization: Bearer $(oc whoami -t)" \
  -H "accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{
    "detectors": {
      "language-detector": {}
    },
    "content": "Hello - can you help me?"
  }' \
  "https://$ORCHESTRATOR_ROUTE/api/v2/text/detection/content" | jq
```

which should return:

```
{
  "detections": [
    {
      "start": 0,
      "end": 24,
      "text": "Hello - can you help me?",
      "detection": "single_label_classification",
      "detection_type": "en",
      "detector_id": "language-detector",
      "score": 0.9464484453201294
    }
  ]
}
```

### Send a request to a guardrailed llm model that should be allowed

```
curl -v \
  -H "Authorization: Bearer $(oc whoami -t)" \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "llm",
    "messages": [
      {
        "content": "Czesc - czy mozesz mi pomoc",
        "role": "user"
      }
    ],
    "detectors": {
      "input": {
        "language-detector": {}
      },
      "output": {
        "language-detector": {}
      }
    }
  }' \
  "https://$ORCHESTRATOR_ROUTE/api/v2/chat/completions-detection" | jq
```

which should return

```
{
  "id": "chat-c8ef177dd7f349c9897c31ced017f788",
  "object": "chat.completion",
  "created": 1760357920,
  "model": "llm",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Cześć! Jak mogę Ci pomóc dalej?"
      },
      "logprobs": null,
      "finish_reason": "stop",
      "stop_reason": null
    }
  ],
  "usage": {
    "prompt_tokens": 39,
    "total_tokens": 53,
    "completion_tokens": 14
  },
  "prompt_logprobs": null
}
```

### Send a request to a guardrailed llm model that should be blocked

```
curl -v \
  -H "Authorization: Bearer $(oc whoami -t)" \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "llm",
    "messages": [
      {
        "content": "Hello - can you help me?",
        "role": "user"
      }
    ],
    "detectors": {
      "input": {
        "language-detector": {}
      },
      "output": {
        "language-detector": {}
      }
    }
  }' \
  "https://$ORCHESTRATOR_ROUTE/api/v2/chat/completions-detection" | jq
```

which should return

```
{
  "id": "8f154a9f8c0c40378c4529468b18fd5f",
  "object": "",
  "created": 1760358109,
  "model": "llm",
  "choices": [],
  "usage": {
    "prompt_tokens": 7,
    "total_tokens": 0,
    "completion_tokens": 0
  },
  "prompt_logprobs": null,
  "detections": {
    "input": [
      {
        "message_index": 0,
        "results": [
          {
            "start": 0,
            "end": 24,
            "text": "Hello - can you help me?",
            "detector_id": "language-detector",
            "detection_type": "en",
            "detection": "single_label_classification",
            "score": 0.9464484453201294
          }
        ]
      }
    ]
  },
  "warnings": [
    {
      "type": "UNSUITABLE_INPUT",
      "message": "Unsuitable input detected. Please check the detected entities on your input and try again with the unsuitable input removed."
    }
  ]
}
```