# Project Knowledge Graph — Graqle SDK

## MISTAKE NODES

### MISTAKE: Manual Lambda Zip Upload Breaks pydantic_core
- **Date:** 2026-03-16
- **Root Cause:** `pip install . -t lambda-repack/` on Windows installs Windows-compiled pydantic_core C extension. Lambda (Linux x86_64) can't load it → `ImportError: No module named 'pydantic_core._pydantic_core'`
- **Fix:** Always deploy via CI/CD (`deploy-lambda.yml`) which builds on `ubuntu-latest` with `--platform manylinux2014_x86_64`
- **Rule:** NEVER use `aws lambda update-function-code --zip-file` from local machine

### MISTAKE: Function URL RESPONSE_STREAM Breaks Mangum
- **Date:** 2026-03-16
- **Root Cause:** Switching Lambda Function URL from `BUFFERED` to `RESPONSE_STREAM` causes Mangum to return raw Lambda proxy envelope (`{"statusCode":200,"body":"..."}`) instead of unwrapped HTTP response
- **Impact:** ALL API endpoints return wrapped JSON — frontend gets `data.nodes = undefined`, shows "No graph available"
- **Fix:** Keep Function URL in `BUFFERED` mode. Mangum handles StreamingResponse within buffered mode.
- **Rule:** NEVER change Function URL InvokeMode to RESPONSE_STREAM

### MISTAKE: Duplicate CORS Headers (ADR-056)
- **Date:** 2026-03-16
- **Root Cause:** FastAPI `CORSMiddleware` adds `Access-Control-Allow-Origin: *` AND Lambda Function URL adds its own CORS header → two headers → browser rejects response entirely
- **Impact:** Graph page shows "trying proxy route..." then "No graph available" — curl works but browsers fail
- **Fix:** Skip CORSMiddleware when `AWS_LAMBDA_FUNCTION_NAME` env var is present (Lambda Function URL is CORS source of truth)
- **Detection:** `curl -sv -H "Origin: https://graqle.com" URL | grep -c "access-control-allow-origin"` — must equal 1
- **Rule:** Single CORS source only. Check infrastructure CORS before adding application CORS.

### MISTAKE: Lambda Timeout Too Short for Reasoning
- **Date:** 2026-03-16
- **Root Cause:** Lambda timeout was 60s (CI/CD default) / 120s (manual). Multi-round reasoning with LLM API calls through VPC NAT Gateway takes 2-5 minutes.
- **Impact:** Reasoning queries return 504 timeout
- **Fix:** Set Lambda timeout to 300s in CI/CD workflow
- **Rule:** Reasoning endpoints need 300s minimum. NAT Gateway adds latency to all external API calls.

## ENVVAR REQUIREMENTS

### Lambda: cognigraph-api (eu-central-1)
| Env Var | Value | Source |
|---------|-------|--------|
| COGNIGRAPH_GRAPH_PATH | s3://graqle-graphs-eu/graqle.json | CI/CD |
| COGNIGRAPH_CONFIG_PATH | s3://graqle-graphs-eu/graqle.yaml | CI/CD |
| COGNIGRAPH_S3_BUCKET | graqle-graphs-eu | CI/CD |
| ANTHROPIC_API_KEY | (from secrets) | GitHub Secrets |
| NEPTUNE_ENDPOINT | graqle-kg.cluster-cfb3tqihxeti.eu-central-1.neptune.amazonaws.com | CI/CD |
| NEPTUNE_PORT | 8182 | CI/CD |
| NEPTUNE_REGION | eu-central-1 | CI/CD |
| NEPTUNE_IAM_AUTH | true | CI/CD |

## INFRASTRUCTURE

### Lambda VPC Configuration
- **Subnets:** Private subnets with NAT Gateway for internet access
- **NAT Gateway:** nat-0121d73d3557c4106
- **S3 Access:** VPC Gateway Endpoint (no NAT needed)
- **Neptune Access:** Same VPC, direct connectivity
- **External APIs (Anthropic/OpenAI):** Through NAT Gateway (adds latency)

### Function URL
- **URL:** https://r3tj3qkjfu6ecxtpw7cb57jbha0qjmaw.lambda-url.eu-central-1.on.aws/
- **InvokeMode:** BUFFERED (NEVER change to RESPONSE_STREAM)
- **CORS:** AllowOrigins: ["*"], AllowHeaders: ["*"], AllowMethods: ["GET","POST","PUT"]
- **Auth:** NONE (public)
