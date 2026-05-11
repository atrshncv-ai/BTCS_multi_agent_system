"""
WhatsApp Client - communicates with local whatsapp-web.js service.
"""

import logging
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

WA_SERVICE_URL = "http://127.0.0.1:3000"


class WhatsAppClient:
    """Client for local WhatsApp service."""
    
    def __init__(self, service_url: str = WA_SERVICE_URL):
        self.service_url = service_url
        self._client = httpx.AsyncClient(timeout=30)
    
    async def get_health(self) -> dict:
        """Check if WhatsApp service is ready."""
        try:
            resp = await self._client.get(f"{self.service_url}/health")
            return resp.json()
        except Exception as e:
            logger.error(f"WA health check failed: {e}")
            return {"status": "error", "isReady": False}
    
    async def is_ready(self) -> bool:
        """Check if WhatsApp is connected and ready."""
        health = await self.get_health()
        return health.get("isReady", False)
    
    async def send_message(self, phone: str, message: str) -> dict:
        """
        Send WhatsApp message.
        
        Args:
            phone: Phone number (format: +7xxx or 7xxx or xxx)
            message: Message text
            
        Returns:
            dict with success status and message details
        """
        try:
            # Format phone
            phone = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
            if not phone.startswith("+"):
                phone = "+" + phone
            
            resp = await self._client.post(
                f"{self.service_url}/send",
                json={"phone": phone, "message": message}
            )
            result = resp.json()
            
            if resp.status_code == 200 and result.get("success"):
                logger.info(f"WA message sent to {phone}")
                return {"success": True, "message_id": result.get("messageId")}
            else:
                logger.error(f"WA send failed: {result.get('error')}")
                return {"success": False, "error": result.get("error")}
                
        except Exception as e:
            logger.error(f"WA send exception: {e}")
            return {"success": False, "error": str(e)}
    
    async def send_contact_message(self, contact: dict, message: str = None) -> dict:
        """
        Send message to contact using their phone number.
        
        Args:
            contact: Contact dict with phones/whatsapp field
            message: Optional custom message (uses default if not provided)
            
        Returns:
            dict with success status
        """
        # Get WhatsApp number
        wa_number = contact.get("whatsapp", "")
        
        # If no WhatsApp, try phones
        if not wa_number:
            phones = contact.get("phones", [])
            if phones:
                wa_number = phones[0]
        
        if not wa_number:
            return {"success": False, "error": "No WhatsApp number"}
        
        # Format message
        from extensions.outreach.outreach_agent import DEFAULT_GREETING
        if message is None:
            name = contact.get("manager_name", "") or "there"
            company = contact.get("company_name", "") or "your company"
            message = DEFAULT_GREETING.format(
                manager_name=name,
                company_name=company
            )
        
        return await self.send_message(wa_number, message)


# Global client instance
_wa_client: Optional[WhatsAppClient] = None


def get_wa_client() -> WhatsAppClient:
    """Get or create WhatsApp client."""
    global _wa_client
    if _wa_client is None:
        _wa_client = WhatsAppClient()
    return _wa_client