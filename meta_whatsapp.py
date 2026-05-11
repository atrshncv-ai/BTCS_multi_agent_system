"""
WhatsApp Cloud API Client (Meta Graph API v25.0)
Прямая отправка сообщений через сервера Facebook
"""

import httpx
import logging
import re
import os
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class MetaWhatsAppClient:
    """Клиент WhatsApp Cloud API"""
    
    def __init__(self):
        self.access_token = os.environ.get('WHATSAPP_META_TOKEN')
        self.phone_number_id = os.environ.get('WHATSAPP_PHONE_ID', '1132578363265135')
        self.api_version = os.environ.get('WHATSAPP_META_VERSION', 'v25.0')
        self.base_url = f"https://graph.facebook.com/{self.api_version}"
        
        if not self.access_token:
            raise ValueError("WHATSAPP_META_TOKEN not set!")
        
        self.client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            },
            timeout=30.0
        )
        
        logger.info(f"✅ MetaWhatsApp initialized | phone_id={self.phone_number_id}")
    
    async def send_text(self, to: str, text: str) -> Dict[str, Any]:
        """Отправить текстовое сообщение"""
        
        formatted_to = self._format_phone(to)
        if not formatted_to:
            return {'success': False, 'error': f'Invalid phone: {to}'}
        
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": formatted_to,
            "type": "text",
            "text": {"body": text[:4096]}
        }
        
        try:
            response = await self.client.post(
                f"{self.base_url}/{self.phone_number_id}/messages",
                json=payload
            )
            
            data = response.json()
            
            if response.status_code == 200 and 'messages' in data:
                msg_id = data['messages'][0]['id']
                logger.info(f"✅ Sent to {formatted_to}")
                return {
                    'success': True,
                    'message_id': msg_id,
                    'contact_phone': formatted_to,
                    'provider': 'meta_cloud'
                }
            
            error_msg = data.get('error', {}).get('message', str(data))
            logger.error(f"❌ Meta error: {error_msg}")
            return {'success': False, 'error': error_msg, 'contact_phone': formatted_to}
            
        except Exception as e:
            logger.error(f"❌ Exception: {e}")
            return {'success': False, 'error': str(e)}
    
    async def send_template(self, to: str, template_name: str = "hello_world") -> Dict[str, Any]:
        """Отправить шаблон (для первых контактов)"""
        
        formatted_to = self._format_phone(to)
        if not formatted_to:
            return {'success': False, 'error': f'Invalid phone: {to}'}
        
        payload = {
            "messaging_product": "whatsapp",
            "to": formatted_to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": "en_US"}
            }
        }
        
        try:
            response = await self.client.post(
                f"{self.base_url}/{self.phone_number_id}/messages",
                json=payload
            )
            
            data = response.json()
            
            if response.status_code == 200 and 'messages' in data:
                return {
                    'success': True,
                    'message_id': data['messages'][0]['id'],
                    'contact_phone': formatted_to,
                    'provider': 'meta_cloud'
                }
            
            return {'success': False, 'error': data.get('error', {}).get('message', str(data))}
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def test_connection(self) -> Dict[str, Any]:
        """Тест подключения"""
        try:
            response = await self.client.get(f"{self.base_url}/{self.phone_number_id}")
            info = response.json()
            
            return {
                'connected': True,
                'display_phone_number': info.get('display_phone_number'),
                'verified_name': info.get('verified_name'),
                'quality_rating': info.get('quality_rating')
            }
        except Exception as e:
            return {'connected': False, 'error': str(e)}
    
    def _format_phone(self, phone: str) -> Optional[str]:
        """Форматирование номера"""
        if not phone:
            return None
        
        cleaned = re.sub(r'[^\d+]', '', phone)
        if cleaned.startswith('+'):
            cleaned = cleaned[1:]
        
        if len(cleaned) < 10:
            return None
        
        return cleaned
    
    async def close(self):
        await self.client.aclose()


_wa_client: Optional[MetaWhatsAppClient] = None


def get_meta_wa_client() -> Optional[MetaWhatsAppClient]:
    """Get or create Meta WhatsApp client"""
    global _wa_client
    if _wa_client is None:
        try:
            _wa_client = MetaWhatsAppClient()
        except ValueError as e:
            logger.warning(f"Meta WhatsApp not configured: {e}")
            return None
    return _wa_client