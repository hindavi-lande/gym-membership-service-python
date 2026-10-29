import json
import urllib.error
import urllib.request

from flask import current_app

from app.errors import ApiError

DEFAULT_TIMEOUT_SECONDS = 5.0


def merge_payments(
    from_member_id: int,
    to_member_id: int,
    base_url: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    base = (base_url or current_app.config["PAYMENTS_SERVICE_URL"]).rstrip("/")
    url = f"{base}/api/payments/merge"
    payload = {"fromMemberId": from_member_id, "toMemberId": to_member_id}
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_body = response.read()
    except urllib.error.HTTPError as exc:
        raise ApiError(
            502, f"Payments service returned {exc.code} for the merge request"
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ApiError(502, "Payments service is unreachable") from exc

    try:
        body = json.loads(raw_body)
    except (TypeError, ValueError) as exc:
        raise ApiError(502, "Payments service returned an invalid response") from exc

    moved = body.get("moved") if isinstance(body, dict) else None
    if not isinstance(moved, int) or isinstance(moved, bool):
        raise ApiError(502, "Payments service returned an invalid response")

    return body
