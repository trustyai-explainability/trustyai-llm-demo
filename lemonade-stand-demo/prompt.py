import argparse
import requests
import json

from requests.exceptions import InvalidURL

# === HELPERS ======================================================================================
bcolor_dict = {
    "PURPLE":   '\033[95m',
    "BLUE":     '\033[94m',
    "CYAN":     '\033[96m',
    "GREEN":    '\033[92m',
    "YELLOW":   '\033[93m',
    "RED":      '\033[91m',
    "ENDC":     '\033[0m',
    "BOLD":     '\033[1m',
    "UNDERLINE":'\033[4m'
}

def bcolor(key, string):
    return bcolor_dict[key.upper()] + string + bcolor_dict['ENDC']


# === COMMON FUNCTIONS =============================================================================
def verbose_print(payload, response):
    print("=== Payload ===")
    print(json.dumps(payload, indent=4))
    print("=== Response ===")
    print(json.dumps(response.json(), indent=4))

def get_headers(cli_args):
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cli_args.token}"
    }


# === COMPLETIONS ENDPOINT =========================================================================
def completions(cli_args):
    payload = {
        "model": cli_args.model,
        "prompt": cli_args.message,
        "temperature": cli_args.temperature,
        "max_tokens": cli_args.max_tokens,
    }
    try:
        response = requests.post(cli_args.url, headers=get_headers(cli_args), json=payload)
    except requests.exceptions.RequestException as e:
        print("ERROR")
        raise e

    if cli_args.verbose:
        verbose_print(payload, response)
        return

    if response.status_code != 200:
        print(bcolor("RED", f"HTTP Error {response.status_code}: {response.text}"))
        return

    response_json = response.json()
    if response_json["choices"]:
        print(bcolor("GREEN", response_json["choices"][0]["text"].strip()))


# === CHAT ENDPOINT =========================================================================
def chat_completions(cli_args):
    payload = {
        "model": cli_args.model,
        "messages": [{"role": "user", "content": cli_args.message}],
        "temperature":cli_args.temperature,
        "max_tokens":cli_args.max_tokens,
    }
    try:
        response = requests.post(cli_args.url, headers=get_headers(cli_args), json=payload)
    except requests.exceptions.RequestException as e:
        print("ERROR")
        raise e

    if response.status_code != 200:
        print(bcolor("RED", f"HTTP Error {response.status_code}: {response.text}"))
        return

    if cli_args.verbose:
        verbose_print(payload, response)
        return

    else:
        response_json = response.json()

        if "detections" in response_json and response_json["detections"] and response_json["warnings"]:
            for warning in response_json["warnings"]:
                print(bcolor("YELLOW", f"Warning: {warning['message']}"))

            message_detections = {}
            for detection_schema, detections_of_that_schema in response_json["detections"].items():
                if detections_of_that_schema is None:
                    continue

                print(bcolor("YELLOW", f"{detection_schema.title()} Detections:"))
                detection_idx = 0
                for msg_idx, detections in enumerate(detections_of_that_schema):
                    for detection in detections['results']:
                        if msg_idx not in message_detections:
                            message_detections[msg_idx] = {}
                        if detection_schema not in message_detections[msg_idx]:
                            message_detections[msg_idx][detection_schema] = []
                        print(bcolor("YELLOW",
                                     f"   {detection_idx}) The {detection['detector_id']} detector flagged the following text: \"{bcolor('UNDERLINE', detection['text'])}\""))
                        detection_idx += 1
        elif response_json["choices"]:
            print(bcolor("GREEN", response_json["choices"][0]["message"]["content"].strip()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="vLLM Client",
    )
    parser.add_argument("--url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--token", default="")
    parser.add_argument("--max_tokens", default=250)
    parser.add_argument("--temperature", default=0)
    parser.add_argument("--verbose", action="store_true")

    args = parser.parse_args()

    if args.url.endswith("v1/chat/completions"):
        chat_completions(args)
    elif args.url.endswith("v1/completions"):
        completions(args)
    else:
        msg = (f"URL must end in either {bcolor('GREEN', 'v1/completions')}"
                         f" or {bcolor('GREEN', 'v1/chat/completions:')},"
                         f" received: {bcolor('RED', args.url)}")
        raise InvalidURL(msg)

