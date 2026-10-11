import json
import os

REQUIRED_RUNTIME_SECRETS = {
    "AUTH_SECRET",
    "DISCORD_APPLICATION_ID",
    "DISCORD_LOG_WEBHOOK_URL",
    "DISCORD_PUBLIC_KEY",
    "DISCORD_STATUS_WEBHOOK_URL",
    "GITHUB_REPO_RAW",
    "GODADDY_API_KEY",
    "GODADDY_API_SECRET",
    "GODADDY_DOMAIN",
    "HETZNER_API_TOKEN",
    "SUPABASE_KEY",
    "SUPABASE_URL",
}


def load_runtime_secrets() -> None:
    secret_arn = os.environ.get("APP_SECRETS_ARN")
    if not secret_arn:
        return

    import boto3

    response = boto3.client(
        "secretsmanager",
        region_name=os.environ.get("AWS_REGION", "eu-central-1"),
    ).get_secret_value(SecretId=secret_arn)
    secret_string = response.get("SecretString")
    if not isinstance(secret_string, str):
        raise RuntimeError("Lambda runtime secret must contain a JSON SecretString")

    try:
        secrets = json.loads(secret_string)
    except json.JSONDecodeError as error:
        raise RuntimeError("Lambda runtime secret is not valid JSON") from error

    if not isinstance(secrets, dict) or any(
        not isinstance(name, str) or not isinstance(value, str)
        for name, value in secrets.items()
    ):
        raise RuntimeError("Lambda runtime secret must be a JSON object of string values")

    missing = REQUIRED_RUNTIME_SECRETS.difference(secrets)
    if missing:
        raise RuntimeError(
            "Lambda runtime secret is missing required settings: "
            + ", ".join(sorted(missing))
        )

    os.environ.update(secrets)
