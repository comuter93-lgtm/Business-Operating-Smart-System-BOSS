from app.core.config import settings


class WhatsAppOTPProvider:
    """WhatsApp OTP delivery via authorized BSP/Meta endpoint only."""

    def is_configured(self) -> bool:
        return bool(settings.whatsapp_otp_provider_url and settings.whatsapp_otp_api_token)

    def status(self) -> dict:
        return {
            "configured": self.is_configured(),
            "status": "READY" if self.is_configured() else "NOT_CONFIGURED",
            "note": "WhatsApp OTP requires an authorized provider URL and token." if not self.is_configured() else "Configured",
        }

