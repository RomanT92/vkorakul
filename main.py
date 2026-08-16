import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
from openai import OpenAI
import requests
import json

# ==========================================
# ÍÀÑÒÐÎÉÊÈ (ÂÑÒÀÂÜÒÅ ÑÂÎÈ ÄÀÍÍÛÅ)
# ==========================================
VK_TOKEN = "vk1.a.Mvn90TUedTR7oGAliJvvGbsUvaxnmfjz8SRM7lvuJLbvfsfHK7kMfOB5YPIPSnEzNBqimGJhEyg1ap078WsZ75jXc4Uc1Bj3J1AnGHq_Ot0ZpeznNiYE2N5HUxNbv_5GjXrSZBzPc1GJ0cgj4PAyl6QlqHxjDzsPpAJZVNCsLQjLLaJTRtJmp-eg-t5zx_A0NFiWnQu-styq0N7A8api_w"
AI_TUNNEL_KEY = "sk-aitunnel-uR0sN0BlJhJNKC1IyNGLVFMvRw5Pv1Xw"
AI_BASE_URL = "https://api.aitunnel.ru/v1/" # Óòî÷íèòå URL â êàáèíåòå AITunnel
GOOGLE_SHEETS_URL = "https://script.google.com/macros/s/AKfycbyeFzUu2-u1N0bJBg9sL4olZOQnoUOciceXxEB9jGzfcrfZD07IYo-LyIP03nx-yAtV/exec"

# ==========================================
# ÈÍÈÖÈÀËÈÇÀÖÈß
# ==========================================
# Ïîäêëþ÷àåìñÿ ê ÂÊ
vk_session = vk_api.VkApi(token=VK_TOKEN)
longpoll = VkLongPoll(vk_session)
vk = vk_session.get_api()

# Ïîäêëþ÷àåìñÿ ê ÈÈ ÷åðåç AITunnel
ai_client = OpenAI(api_key=AI_TUNNEL_KEY, base_url=AI_BASE_URL)

# Ñèñòåìíûé ïðîìïò: îáúÿñíÿåì ÈÈ, êàê îí äîëæåí îòâå÷àòü
SYSTEM_PROMPT = """
Òû — óìíûé ôèíàíñîâûé àññèñòåíò. Ïîëüçîâàòåëü ïèøåò òåáå ñâîè òðàòû èëè äîõîäû.
Òâîÿ çàäà÷à — èçâëå÷ü äàííûå è âåðíóòü èõ ÑÒÐÎÃÎ â ôîðìàòå JSON, áåç ëèøíåãî òåêñòà.
Ôîðìàò JSON:
{
  "item": "Íàçâàíèå ïîêóïêè/îïåðàöèè",
  "amount": 1500,
  "type": "Ðàñõîä" (èëè "Äîõîä"),
  "comment": "ëþáîé êîììåíòàðèé ïîëüçîâàòåëÿ"
}
Åñëè ïîëüçîâàòåëü ïðîñòî îáùàåòñÿ, îòâå÷àé îáû÷íûì òåêñòîì (íå JSON).
"""

def send_vk_message(user_id, text):
    """Ôóíêöèÿ îòïðàâêè ñîîáùåíèÿ â ÂÊ"""
    vk.messages.send(user_id=user_id, message=text, random_id=0)

def send_to_google_sheets(payload):
    """Ôóíêöèÿ îòïðàâêè äàííûõ â íàøó òàáëèöó"""
    try:
        response = requests.post(GOOGLE_SHEETS_URL, json=payload)
        return response.json()
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

print("Áîò óñïåøíî çàïóùåí è ñëóøàåò ÂÊ...")

# ==========================================
# ÃËÀÂÍÛÉ ÖÈÊË ÁÎÒÀ
# ==========================================
for event in longpoll.listen():
    if event.type == VkEventType.MESSAGE_NEW and event.to_me:
        user_id = event.user_id
        user_text = event.text
        
        # Îòïðàâëÿåì ÈÈ ñîîáùåíèå ïîëüçîâàòåëÿ
        try:
            ai_response = ai_client.chat.completions.create(
                model="gpt-3.5-turbo", # Èëè gpt-4o-mini, â çàâèñèìîñòè îò AITunnel
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_text}
                ]
            )
            reply_text = ai_response.choices[0].message.content.strip()
            
            # Ïðîâåðÿåì, âåðíóë ëè ÈÈ JSON (ïîõîæå ëè ýòî íà òðàíçàêöèþ)
            if reply_text.startswith("{") and reply_text.endswith("}"):
                try:
                    # Ðàñïàêîâûâàåì JSON îò ÈÈ
                    transaction_data = json.loads(reply_text)
                    
                    # Îòïðàâëÿåì ïîëüçîâàòåëþ ñîîáùåíèå, ÷òî íà÷àëè îáðàáîòêó
                    send_vk_message(user_id, f"? Çàïèñûâàþ: {transaction_data['item']} íà {transaction_data['amount']} ðóá...")
                    
                    # Îòïðàâëÿåì â Google Òàáëèöó
                    gs_response = send_to_google_sheets(transaction_data)
                    
                    # Îáðàáàòûâàåì îòâåò îò òàáëèöû
                    if gs_response.get("status") == "SUCCESS":
                        send_vk_message(user_id, "? Óñïåøíî çàïèñàíî â òàáëèöó!")
                    elif gs_response.get("status") == "SUCCESS_AUTO_ADDED":
                        send_vk_message(user_id, f"? Çàïèñàíî! Àâòîìàòè÷åñêè îïðåäåëèë êàòåãîðèþ: {gs_response.get('recognized_cat')} -> {gs_response.get('recognized_sub')}")
                    elif gs_response.get("status") == "UNKNOWN_ITEM":
                        # Åñëè òàáëèöà íå çíàåò ñëîâî, îòïðàâëÿåì ìåíþ ïîëüçîâàòåëþ
                        send_vk_message(user_id, "?? ß íå çíàþ ýòó ñòàòüþ. Êóäà åå îòíåñòè? Íàïèøè êàòåãîðèþ.")
                        # Â áóäóùåì çäåñü ìîæíî äîáàâèòü ëîãèêó êíîïîê (Inline Keyboards) ÂÊ
                    else:
                        send_vk_message(user_id, f"? Îøèáêà òàáëèöû: {gs_response.get('message')}")
                        
                except json.JSONDecodeError:
                    send_vk_message(user_id, "? Îøèáêà: ÈÈ âåðíóë íåïðàâèëüíûé ôîðìàò äàííûõ.")
            else:
                # Åñëè ÈÈ âåðíóë îáû÷íûé òåêñò (ïðîñòî îáùåíèå)
                send_vk_message(user_id, reply_text)
                
        except Exception as e:
            send_vk_message(user_id, "? Îøèáêà ñâÿçè ñ ÈÈ.")
            print(f"Îøèáêà: {e}")
