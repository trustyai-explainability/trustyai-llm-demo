# Introduction

This is a proof-of-concept demo for demonstrating the potential usage of [custom chunkers](https://github.com/m-misiura/guardrails-chunkers) with the TrustyAI Guardrails orchestrator.

The demo will let you deploy

- a [chunker service](https://github.com/m-misiura/guardrails-chunkers/blob/main/chunkers/grpc_server.py) with three available chunking strategies:
    - [sentence-based](https://github.com/m-misiura/guardrails-chunkers/blob/main/chunkers/sentence_chunker.py) chunking based on a pre-defined regex pattern
    - [langchain wrapper](https://github.com/m-misiura/guardrails-chunkers/blob/main/chunkers/chunker_factory.py) around their recursive and non-recursive character-based chunking

    this chunker service can be used as a standalone service or can be used as part of the Guardrails orchestrator
- a Guardrails orchestrator with [built-in detectors](https://github.com/trustyai-explainability/guardrails-detectors/tree/main/detectors/built_in) as well as the [IBM HAP model](https://huggingface.co/ibm-granite/granite-guardian-hap-38m) using the [Hugging Face detector](https://github.com/trustyai-explainability/guardrails-detectors/tree/main/detectors/huggingface)


# Setup 

1. Using, e.g. `oc` create a new project/namespace, named `testing`:

```bash
oc new-project testing
```

2. Use oc apply -k to deploy all the resources:

```bash
oc apply -k guardrails-chunkers-demo
```

# Requests

## Chunker 

Port-forward the chunker service:

```bash
oc port-forward service/chunker-service 8085:8085
```

### List available services

```bash
grpcurl \
  -plaintext \
  localhost:8085 \
  list
```

__Expected output:__

```
caikit.runtime.Chunkers.ChunkersService
grpc.health.v1.Health
grpc.reflection.v1alpha.ServerReflection
```

### Health check

```
grpcurl \
    -plaintext \
    localhost:8085 \
    grpc.health.v1.Health/Check
```

__Expected output:__

```
{
  "status": "SERVING"
}
```
### Test sentence chunker

```
grpcurl \
    -plaintext \
    -H "mm-model-id: sentence" \
    -d '{"text": "Hello world. This is a test. This is a yet another test"}' \
    localhost:8085 \
    caikit.runtime.Chunkers.ChunkersService/ChunkerTokenizationTaskPredict
```

__Expected output:__

```
{
  "results": [
    {
      "end": "12",
      "text": "Hello world."
    },
    {
      "start": "13",
      "end": "28",
      "text": "This is a test."
    },
    {
      "start": "29",
      "end": "55",
      "text": "This is a yet another test"
    }
  ],
  "token_count": "3"
}
```

### Test langchain_character chunker

```
grpcurl \
    -plaintext \
    -H "mm-model-id: langchain_character" \
    -d '{
        "text": "First paragraph of a very long document to demonstrate how this chunking algorithm would work; we set the chunk sizes to be of max size of xxx characters with no overlap.\n\nSecond paragraph.\n\nThird paragraph."
    }' \
    localhost:8085 \
    caikit.runtime.Chunkers.ChunkersService/ChunkerTokenizationTaskPredict
```

__Expected output:__

```
{
  "results": [
    {
      "end": "170",
      "text": "First paragraph of a very long document to demonstrate how this chunking algorithm would work; we set the chunk sizes to be of max size of xxx characters with no overlap."
    },
    {
      "start": "172",
      "end": "207",
      "text": "Second paragraph.\n\nThird paragraph."
    }
  ],
  "token_count": "2"
}
```

### Test langchain_recursive_character chunker

```
grpcurl \
    -plaintext \
    -H "mm-model-id: langchain_recursive_character" \
    -d '{
        "text": "First paragraph of a very long document to demonstrate how this chunking algorithm would work; we set the chunk sizes to be of max size of xxx characters with no overlap.\n\nSecond paragraph.\n\nThird paragraph."
    }' \
    localhost:8085 \
    caikit.runtime.Chunkers.ChunkersService/ChunkerTokenizationTaskPredict
```

__Expected output:__

```
{
  "results": [
    {
      "end": "97",
      "text": "First paragraph of a very long document to demonstrate how this chunking algorithm would work; we"
    },
    {
      "start": "98",
      "end": "170",
      "text": "set the chunk sizes to be of max size of xxx characters with no overlap."
    },
    {
      "start": "172",
      "end": "207",
      "text": "Second paragraph.\n\nThird paragraph."
    }
  ],
  "token_count": "3"
}
```

## Orchestrator 

- Get the external route of the main orchestrator service:

```bash
export FMS_ORCHESTRATOR_URL="https://$(oc get routes guardrails-orchestrator  -o jsonpath='{.spec.host}')"
```

- Get the external route of the health orchestrator service:

```bash
export FMS_ORCHESTRATOR_HEALTH_URL="https://$(oc get routes guardrails-orchestrator-health  -o jsonpath='{.spec.host}')"
```

### Health check

```bash
curl -k $FMS_ORCHESTRATOR_HEALTH_URL/info | jq
```

__Expected output__:

```
{
  "services": {
    "langchain_recursive_character": {
      "status": "HEALTHY"
    },
    "built-in-detector": {
      "status": "HEALTHY"
    },
    "ibm-hap-38m-detector": {
      "status": "HEALTHY"
    },
    "sentence": {
      "status": "HEALTHY"
    }
  }
}
```

### Test api/v2/text/detection/content -- trigger HAP

```
curl \
  -H "accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{
    "detectors": {
      "ibm-hap-38m-detector": {}
    },
    "content": "This is the first paragraph with multiple sentences. It contains several thoughts and ideas that belong together.\n\nThis is the second paragraph with different content. It discusses a separate topic from the first paragraph.\n\nThis is the third paragraph with concluding thoughts. It wraps up the discussion from the previous paragraphs. and btw I hate you you absoluet dotard"
  }' \
  "$FMS_ORCHESTRATOR_URL/api/v2/text/detection/content" | jq
```

__Expected output__

```
{
  "detections": [
    {
      "start": 279,
      "end": 374,
      "text": "It wraps up the discussion from the previous paragraphs. and btw I hate you you absoluet dotard",
      "detection": "single_label_classification",
      "detection_type": "LABEL_1",
      "detector_id": "ibm-hap-38m-detector",
      "score": 0.7825431823730469
    }
  ]
}
```

In the chunker service logs you should see that the `sentence` chunker was used:

```
025-10-03 16:18:16,314 - __main__ - INFO - gRPC request received: /caikit.runtime.Chunkers.ChunkersService/ChunkerTokenizationTaskPredict
2025-10-03 16:18:16,314 - __main__ - INFO - gRPC request completed: /caikit.runtime.Chunkers.ChunkersService/ChunkerTokenizationTaskPredict
2025-10-03 16:18:16,314 - __main__ - INFO - Received chunking request: model_id=sentence, text_length=374
2025-10-03 16:18:16,314 - __main__ - INFO - Chunking complete: model_id=sentence, chunks=6
2025-10-03 16:18:16,314 - __main__ - INFO - Sending response: token_count=6
```

### Test api/v2/text/detection/content -- trigger built-in detector

```
curl \
  -H "accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{
    "detectors": {
      "built-in-detector": {
        "regex": ["email"]
      }
    },
    "content": "This is the first paragraph with multiple sentences. It contains several thoughts and ideas that belong together.\n\nThis is the second paragraph with different content. It discusses a separate topic from the first paragraph.\n\nThis is the third paragraph with concluding thoughts. It wraps up the discussion from the previous paragraphs. and btw I my email is test@domain.com"
  }' \
  "$FMS_ORCHESTRATOR_URL/api/v2/text/detection/content" | jq
```

__Expected output__

```
{
  "detections": [
    {
      "start": 358,
      "end": 373,
      "text": "test@domain.com",
      "detection": "email_address",
      "detection_type": "pii",
      "detector_id": "built-in-detector",
      "score": 1.0
    }
  ]
}
```

In the chunker service logs you should see that the `langchain_recursive_character` chunker was used:

```
2025-10-03 16:22:54,329 - __main__ - INFO - gRPC request received: /caikit.runtime.Chunkers.ChunkersService/ChunkerTokenizationTaskPredict
2025-10-03 16:22:54,329 - __main__ - INFO - gRPC request completed: /caikit.runtime.Chunkers.ChunkersService/ChunkerTokenizationTaskPredict
2025-10-03 16:22:54,329 - __main__ - INFO - Received chunking request: model_id=langchain_recursive_character, text_length=373
2025-10-03 16:22:54,330 - __main__ - INFO - Chunking complete: model_id=langchain_recursive_character, chunks=6
2025-10-03 16:22:54,330 - __main__ - INFO - Sending response: token_count=6
```