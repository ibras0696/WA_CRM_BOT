from typing import List
import logging

import requests

from crm_bot.config import settings


class WhatsKeyboardClient:
    def __init__(self, base_url: str, api_token: str, id_instance: str):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.id_instance = id_instance
        # self.headers = {
        #     "Content-Type": "application/json",
        #     "Authorization": f"Bearer {api_token}",
        # }

    def __call__(
        self,
        chat_id: str,
        body: str,
        buttons: List[str],
        header: str | None = None,
        footer: str | None = None,
        payload: dict | None = None,
    ) -> dict:
        """
        Отправка интерактивных кнопок в WhatsApp.
        buttons — список текстов кнопок.
        :param chat_id: Идентификатор чата (например, номер телефона с суффиксом @c.us)
        :param body: Основной текст сообщения
        :param buttons: Список текстов кнопок
        :param header: Заголовок сообщения (необязательно)
        :param footer: Нижний колонтитул сообщения (необязательно)
        :return: Ответ API в виде словаря
        """

        payload = {
            "chatId": chat_id,
            "body": body,
            "buttons": self._build_buttons(buttons),
        }

        if header:
            payload["header"] = header
        if footer:
            payload["footer"] = footer

        url = (
            f"{self.base_url}"
            f"/waInstance{self.id_instance}"
            f"/sendInteractiveButtonsReply"
            f"/{self.api_token}"
        )
        resp = requests.post(
            url=url,
            # f"{self.base_url}/waInstance{self.id_instance}/sendInteractiveButtonsReply/",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_token}",
            },
            json=payload,
            timeout=10,
        )

        logging.debug(f"WA keyboard response: {resp.status_code} {resp.text}")
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _build_buttons(button_texts: List[str]) -> list[dict]:
        """
        Преобразует:
        ["Да", "Нет"]
        →
        [
            {"buttonId": "1", "buttonText": "Да"},
            {"buttonId": "2", "buttonText": "Нет"},
        ]
        """
        return [
            {
                "buttonId": str(index + 1),
                "buttonText": text,
            }
            for index, text in enumerate(button_texts)
        ]

base_wa_kb_sender = WhatsKeyboardClient(
    base_url=settings.green_api_host, 
    api_token=settings.api_token, 
    id_instance=settings.id_instance
)

if __name__ == "__main__":
    # Пример использования
    response = base_wa_kb_sender(
        chat_id='79323056361@c.us',
        body='Боди',
        header='Заголовок',
        buttons=['1', '2', '3']
    )
