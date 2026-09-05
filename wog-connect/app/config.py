from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _bool(val: str | None, default: bool = False) -> bool:
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    portal_user: str
    portal_password: str
    portal_accounts: dict[str, str]
    api_key: str
    data_dir: Path
    incoming_dir: Path
    delivery_proofs_export_dir: Path
    post_client_id: str
    post_client_secret: str
    post_oauth_token_url: str
    post_oauth_scope: str
    post_address_oauth_scope: str
    post_address_validate_url: str
    post_address_validate_enabled: bool
    post_address_validate_strict: bool
    post_barcode_url: str
    post_franking_license: str
    post_language: str
    post_przl: list[str]
    post_label_layout: str
    post_label_image_type: str
    post_label_resolution: int
    post_print_preview: bool
    post_label_sender_from_soloplan: bool
    post_sender_name1: str
    post_sender_street: str
    post_sender_zip: str
    post_sender_city: str
    post_sender_country: str
    post_notifications_enabled: bool
    post_notification_services: list[int]
    post_notification_language: str
    default_weight_grams: int
    consignment_reference_filter: str
    carrier_matchcode_filter: str
    session_secret: str
    label_logo_enabled: bool
    label_logo_path: Path
    label_logo_width_pt: float
    shippingnet_enabled: bool
    shippingnet_base_url: str
    shippingnet_email: str
    shippingnet_password: str
    portal_ablieferbeleg_enabled: bool
    portal_ablieferbeleg_base_url: str
    portal_ablieferbeleg_api_key: str


def _parse_portal_accounts(primary_user: str, primary_password: str) -> dict[str, str]:
    """PORTAL_USER/PASSWORD plus optionale Extra-Konten aus PORTAL_EXTRA_USERS.

    Format PORTAL_EXTRA_USERS: user:password;user2:password2
    (erstes ":" trennt Name und Passwort; mehrere Konten mit ";").
    """
    accounts: dict[str, str] = {}
    if primary_user and primary_password:
        accounts[primary_user] = primary_password
    extra = os.getenv("PORTAL_EXTRA_USERS", "").strip()
    if extra:
        for part in extra.split(";"):
            part = part.strip()
            if not part or ":" not in part:
                continue
            user, pw = part.split(":", 1)
            user, pw = user.strip(), pw.strip()
            if user and pw:
                accounts[user] = pw
    return accounts


def get_settings() -> Settings:
    data_dir = Path(os.getenv("WOG_CONNECT_DATA_DIR", "/opt/wog-connect/data"))
    incoming_dir = Path(os.getenv("WOG_CONNECT_INCOMING_DIR", "/opt/wog-connect/incoming"))
    app_dir = Path(__file__).resolve().parent
    default_logo = app_dir / "assets" / "wog-logo.png"
    przl = [p.strip() for p in os.getenv("POST_PRZL", "PRI").split(",") if p.strip()]
    notif = [
        int(x.strip())
        for x in os.getenv("POST_NOTIFICATION_SERVICES", "1").split(",")
        if x.strip().isdigit()
    ]
    portal_user = os.getenv("PORTAL_USER", "Portaladmin")
    portal_password = os.getenv("PORTAL_PASSWORD", "")
    return Settings(
        portal_user=portal_user,
        portal_password=portal_password,
        portal_accounts=_parse_portal_accounts(portal_user, portal_password),
        api_key=os.getenv("WOG_CONNECT_API_KEY", ""),
        data_dir=data_dir,
        incoming_dir=incoming_dir,
        delivery_proofs_export_dir=Path(
            os.getenv(
                "WOG_CONNECT_DELIVERY_PROOFS_DIR",
                str(incoming_dir / "delivery_proofs"),
            )
        ),
        post_client_id=os.getenv("POST_CLIENT_ID", ""),
        post_client_secret=os.getenv("POST_CLIENT_SECRET", ""),
        post_oauth_token_url=os.getenv("POST_OAUTH_TOKEN_URL", "https://api.post.ch/OAuth/token"),
        post_oauth_scope=os.getenv("POST_OAUTH_SCOPE", "DCAPI_BARCODE_READ"),
        post_address_oauth_scope=os.getenv("POST_ADDRESS_OAUTH_SCOPE", "DCAPI_ADDRESS_VALIDATE"),
        post_address_validate_url=os.getenv(
            "POST_ADDRESS_VALIDATE_URL",
            "https://dcapi.apis.post.ch/address/v1/addresses/validation",
        ),
        post_address_validate_enabled=_bool(os.getenv("POST_ADDRESS_VALIDATE_ENABLED"), True),
        post_address_validate_strict=_bool(os.getenv("POST_ADDRESS_VALIDATE_STRICT"), False),
        post_barcode_url=os.getenv(
            "POST_BARCODE_URL", "https://dcapi.apis.post.ch/barcode/v1/generateAddressLabel"
        ),
        post_franking_license=os.getenv("POST_FRANKING_LICENSE", ""),
        post_language=os.getenv("POST_LANGUAGE", "DE"),
        post_przl=przl or ["PRI"],
        post_label_layout=os.getenv("POST_LABEL_LAYOUT", "A6"),
        post_label_image_type=os.getenv("POST_LABEL_IMAGE_TYPE", "PDF"),
        post_label_resolution=int(os.getenv("POST_LABEL_RESOLUTION", "300")),
        post_print_preview=_bool(os.getenv("POST_PRINT_PREVIEW"), False),
        post_label_sender_from_soloplan=_bool(os.getenv("POST_LABEL_SENDER_FROM_SOLOPLAN"), True),
        post_sender_name1=os.getenv("POST_SENDER_NAME1", "WOG Logistics AG"),
        post_sender_street=os.getenv("POST_SENDER_STREET", "Wildenaustraße 22"),
        post_sender_zip=os.getenv("POST_SENDER_ZIP", "9444"),
        post_sender_city=os.getenv("POST_SENDER_CITY", "Diepoldsau"),
        post_sender_country=os.getenv("POST_SENDER_COUNTRY", "CH"),
        post_notifications_enabled=_bool(os.getenv("POST_NOTIFICATIONS_ENABLED"), False),
        post_notification_services=notif or [1],
        post_notification_language=os.getenv("POST_NOTIFICATION_LANGUAGE", "DE"),
        default_weight_grams=int(os.getenv("DEFAULT_WEIGHT_GRAMS", "1000")),
        consignment_reference_filter=os.getenv("CONSIGNMENT_REFERENCE_FILTER", "DPD,POST").upper(),
        carrier_matchcode_filter=os.getenv("CARRIER_MATCHCODE_FILTER", "").upper(),
        session_secret=os.getenv("WOG_CONNECT_SESSION_SECRET", os.getenv("WOG_CONNECT_API_KEY", "dev-secret")),
        label_logo_enabled=_bool(os.getenv("LABEL_LOGO_ENABLED"), True),
        label_logo_path=Path(os.getenv("LABEL_LOGO_PATH", str(default_logo))),
        label_logo_width_pt=float(os.getenv("LABEL_LOGO_WIDTH_PT", "68")),
        shippingnet_enabled=_bool(os.getenv("SHIPPINGNET_ENABLED"), False),
        shippingnet_base_url=os.getenv("SHIPPINGNET_BASE_URL", "https://wog.logistikberater.at").rstrip("/"),
        shippingnet_email=os.getenv("SHIPPINGNET_EMAIL", "").strip(),
        shippingnet_password=os.getenv("SHIPPINGNET_PASSWORD", ""),
        portal_ablieferbeleg_enabled=_bool(os.getenv("WOG_PORTAL_ABLIEFERBELEG_ENABLED"), True),
        portal_ablieferbeleg_base_url=os.getenv(
            "WOG_PORTAL_ABLIEFERBELEG_BASE_URL",
            os.getenv("SHIPPINGNET_BASE_URL", "https://wog.logistikberater.at"),
        ).rstrip("/"),
        portal_ablieferbeleg_api_key=os.getenv("WOG_PORTAL_ABLIEFERBELEG_API_KEY", "").strip(),
    )
