import os
import json
import base64
import asyncio
import websockets
import logging
from itertools import groupby
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.websockets import WebSocketDisconnect
import vonage
from datetime import datetime

# THIS IS NOT USED... THIS IS ALTERNATIVE FOR TWILIO
# NEED TO TEST... 

# Vonage-konfiguraatio
VONAGE_APPLICATION_ID = os.getenv("VONAGE_APPLICATION_ID")
VONAGE_PRIVATE_KEY = os.getenv("VONAGE_PRIVATE_KEY")  # Polku private key -tiedostoon
VONAGE_NUMBER = os.getenv("VONAGE_NUMBER")
WEBHOOK_BASE_URL = os.getenv("LOCALTUNNEL_URL")  # Sama kuin LOCALTUNNEL_URL, vain nimi vaihtui

SYSTEM_MESSAGE = (
    "You are a journalist conducting a relaxed and friendly interview in Finnish. "
    "Begin by greeting and briefly explaining that you are doing a quick interview about the use of artificial intelligence in newsrooms and the limits of AI compared to humans. "
    "Ask only one question at a time, in the exact order listed below. Wait for an answer before moving to the next question. "
    "Under no circumstances should you answer any of the questions yourself, or move to the next question before the interviewee has answered. "
    "Use a natural, conversational, and friendly tone, as if you were a real person. "
    "Speak only Finnish; do not use any English words or expressions. "
    "Once all questions have been answered, politely thank the interviewee, say that these were all your questions, wish them a good day, and let them know they can now end the call. "
    "Remember: Your job is to ask the questions and listen. Never answer the questions yourself, under any circumstances. "
    "Remember to speak only Finnish! This is very important."
    "Here are the questions:\n"
    "1. Mitä riskejä liittyy siihen, että tekoäly tekee itsenäisesti julkaisupäätöksiä?\n"
    "2. Mitkä toimitustehtävät kannattaa yhä jättää ihmisille?"
)

TRANSCRIPTION_PROMPT = (
    "Tämä on reaaliaikainen suomenkielinen haastattelu. "
    "Keskustelu voi sisältää kysymyksiä, spontaaneja vastauksia, täytesanoja ja erikoistermejä. "
    "Kirjoita kaikki sanat tarkasti ja selkeästi, säilytä välimerkit ja luonnolliset tauot aina kun mahdollista."
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from vonage import Vonage, Auth
from vonage_voice import CreateCallRequest

# Vonage-client - Versio 4.x syntaksi
auth = Auth(
    application_id=VONAGE_APPLICATION_ID,
    private_key=VONAGE_PRIVATE_KEY
)
vonage_client = Vonage(auth=auth)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
VOICE = "shimmer"

LOG_EVENT_TYPES = [
    "error",
    "response.content.done",
    "rate_limits.updated",
    "response.done",
    "input_audio_buffer.committed",
    "input_audio_buffer.speech_stopped",
    "input_audio_buffer.speech_started",
    "session.created",
]
SHOW_TIMING_MATH = False

app = FastAPI()
conversation_logs = {}


def setup_vonage_routes(app: FastAPI):
    """Setup all Vonage-related routes on the FastAPI app"""

    @app.api_route("/answer", methods=["GET", "POST"])
    async def handle_answer_webhook(request: Request):
        """Vonage webhook for incoming calls"""
        try:
            # NCCO (Nexmo Call Control Object) - Vonagen versio TwiML:stä
            ncco = [
                {
                    "action": "talk",
                    "text": "Yhdistän sinut haastatteluun.",
                    "language": "fi-FI"
                },
                {
                    "action": "connect",
                    "from": VONAGE_NUMBER,
                    "endpoint": [
                        {
                            "type": "websocket",
                            "uri": f"{WEBHOOK_BASE_URL.replace('https://', 'wss://')}/websocket",
                            "content-type": "audio/l16;rate=16000"
                        }
                    ]
                }
            ]

            logger.info("Incoming call handled, connecting to WebSocket")
            return JSONResponse(content=ncco)

        except Exception as e:
            logger.error(f"Error handling incoming call: {e}")
            ncco = [
                {
                    "action": "talk",
                    "text": "Pahoittelemme, puhelun yhdistämisessä tapahtui virhe. Yritä myöhemmin uudelleen.",
                    "language": "fi-FI"
                }
            ]
            return JSONResponse(content=ncco)

    @app.post("/start-interview")
    async def start_interview(request: Request):
        """Start an interview call using Vonage Voice API"""
        try:
            try:
                body = await request.json()
            except Exception as json_error:
                logger.error(f"JSON parsing error: {json_error}")
                return JSONResponse(
                    status_code=400, content={"error": "Invalid JSON in request body"}
                )

            phone_number = body.get("phone_number")
            system_prompt = body.get("system_prompt")
            language = body.get("language", "fi")
            interview_context = body.get("interview_context", "")

            if not phone_number:
                return JSONResponse(
                    status_code=400, content={"error": "phone_number is required"}
                )
            if not system_prompt:
                return JSONResponse(
                    status_code=400, content={"error": "system_prompt is required"}
                )

            if not VONAGE_NUMBER:
                return JSONResponse(
                    status_code=400,
                    content={"error": "Missing VONAGE_NUMBER environment variable"},
                )
            if not WEBHOOK_BASE_URL:
                return JSONResponse(
                    status_code=400,
                    content={"error": "Missing WEBHOOK_BASE_URL environment variable"},
                )

            global SYSTEM_MESSAGE
            original_message = SYSTEM_MESSAGE
            SYSTEM_MESSAGE = system_prompt

            # Määritä NCCO
            ncco = [
                {
                    "action": "talk",
                    "text": "Yhdistän sinut haastatteluun.",
                    "language": "fi-FI"
                },
                {
                    "action": "connect",
                    "from": VONAGE_NUMBER,
                    "endpoint": [
                        {
                            "type": "websocket",
                            "uri": f"{WEBHOOK_BASE_URL.replace('https://', 'wss://')}/websocket",
                            "content-type": "audio/l16;rate=16000"
                        }
                    ]
                }
            ]

            # Vonage-pyyntö on korjattu tässä
            call_request = CreateCallRequest(
                to=[{'type': 'phone', 'number': phone_number}],
                from_={'type': 'phone', 'number': VONAGE_NUMBER},
                ncco=ncco
            )

            response = vonage_client.voice.create_call(call_request)
            call_uuid = response.uuid
            
            logger.info(
                f"Vonage interview call initiated - UUID: {call_uuid}, To: {phone_number}"
            )
            logger.info(f"Interview context: {interview_context}")

            conversation_logs[call_uuid] = []

            return JSONResponse(
                content={
                    "status": "success",
                    "call_uuid": call_uuid,
                    "message": f"Interview call initiated to {phone_number}",
                    "to_number": phone_number,
                    "from_number": VONAGE_NUMBER,
                    "language": language,
                    "interview_context": interview_context,
                }
            )

        except Exception as e:
            logger.error(f"Error starting Vonage interview: {e}")
            return JSONResponse(
                status_code=500,
                content={"error": f"Failed to start interview: {str(e)}"},
            )
        finally:
            async def restore_message():
                await asyncio.sleep(300)
                global SYSTEM_MESSAGE
                SYSTEM_MESSAGE = original_message
                logger.info("System message restored to default")
            asyncio.create_task(restore_message())

    @app.post("/trigger-call")
    async def trigger_call():
        """Trigger a default call using environment variables"""
        try:
            if not VONAGE_NUMBER:
                return JSONResponse(
                    status_code=400,
                    content={"error": "Missing VONAGE_NUMBER environment variable"},
                )

            to_number = os.getenv("WHERE_TO_CALL")
            if not to_number:
                return JSONResponse(
                    status_code=400,
                    content={"error": "Missing WHERE_TO_CALL environment variable"},
                )

            if not WEBHOOK_BASE_URL:
                return JSONResponse(
                    status_code=400,
                    content={"error": "Missing WEBHOOK_BASE_URL environment variable"},
                )

            ncco = [
                {
                    "action": "talk",
                    "text": "Yhdistän sinut haastatteluun.",
                    "language": "fi-FI"
                },
                {
                    "action": "connect",
                    "from": VONAGE_NUMBER,
                    "endpoint": [
                        {
                            "type": "websocket",
                            "uri": f"{WEBHOOK_BASE_URL.replace('https://', 'wss://')}/websocket",
                            "content-type": "audio/l16;rate=16000"
                        }
                    ]
                }
            ]
            
            print("TÄÄÄÄÄ!!!")
            print(ncco)

            # Vonage-pyyntö on korjattu tässä
            call_request = CreateCallRequest(
                to=[{'type': 'phone', 'number': to_number}],
                #from_={'type': 'phone', 'number': VONAGE_NUMBER},
                ncco=ncco,
                random_from_number=True
            )

            response = vonage_client.voice.create_call(call_request)
            call_uuid = response.uuid
            
            logger.info(
                f"Default Vonage call initiated - UUID: {call_uuid}, To: {to_number}"
            )
            
            conversation_logs[call_uuid] = []

            return JSONResponse(
                content={
                    "status": "success",
                    "call_uuid": call_uuid,
                    "message": f"Call initiated to {to_number}",
                    "to_number": to_number,
                    "from_number": VONAGE_NUMBER,
                }
            )

        except Exception as e:
            logger.error(f"Error initiating Vonage call: {e}")
            return JSONResponse(
                status_code=500, content={"error": f"Failed to initiate call: {str(e)}"}
            )

    @app.websocket("/websocket")
    async def handle_websocket_connection(websocket: WebSocket):
        """Handle Vonage WebSocket connection for real-time audio"""
        logger.info("Vonage WebSocket connection established")
        await websocket.accept()

        if not OPENAI_API_KEY:
            logger.error("OpenAI API key not configured")
            await websocket.close(code=1008, reason="OpenAI API key not configured")
            return

        openai_ws = None
        call_uuid = None
        latest_media_timestamp = 0
        last_assistant_item = None
        mark_queue = []
        response_start_timestamp = None
        call_ended = False
        
        try:
            logger.info("Connecting to OpenAI Realtime API...")
            openai_ws = await websockets.connect(
                "wss://api.openai.com/v1/realtime",
                additional_headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "OpenAI-Beta": "realtime=v1",
                },
            )
            logger.info("Successfully connected to OpenAI")
            
            await initialize_session(openai_ws)

            async def receive_from_vonage():
                nonlocal call_uuid, latest_media_timestamp, call_ended
                logger.info("Starting receive_from_vonage task")
                try:
                    async for message in websocket.iter_text():
                        # Vonage WebSocket viestien käsittely
                        if message:
                            # Vonage lähettää audio dataa base64-enkoodattuna
                            # Tämä pitää muuntaa OpenAI:lle sopivaan muotoon
                            try:
                                audio_data = base64.b64decode(message)
                                # Muunna L16 16kHz -> muLaw 8kHz OpenAI:lle
                                # Tämä on yksinkertaistettu - oikeassa toteutuksessa tarvitsisi
                                # kunnollisen audio resampling -kirjaston
                                audio_b64 = base64.b64encode(audio_data).decode()
                                
                                await openai_ws.send(
                                    json.dumps({
                                        "type": "input_audio_buffer.append",
                                        "audio": audio_b64,
                                    })
                                )
                            except Exception as e:
                                logger.error(f"Error processing Vonage audio: {e}")

                except WebSocketDisconnect:
                    logger.info("Vonage WebSocket disconnected")
                    call_ended = True
                except Exception as e:
                    logger.error(f"Error in receive_from_vonage: {e}")
                    call_ended = True
                finally:
                    logger.info("receive_from_vonage task ending")

            async def send_to_vonage():
                nonlocal call_uuid, last_assistant_item, response_start_timestamp, call_ended
                logger.info("Starting send_to_vonage task")
                try:
                    async for openai_message in openai_ws:
                        if call_ended:
                            logger.info("Call has ended, stopping send_to_vonage")
                            break
                            
                        response = json.loads(openai_message)
                        
                        if response.get("type") == "session.created":
                            logger.info("OpenAI session created successfully")

                        if response.get("type") == "error":
                            logger.error(f"OpenAI error: {response}")
                            continue

                        if response.get("type") == "conversation.item.input_audio_transcription.completed":
                            transcript_text = response.get("transcript", "").strip()
                            if transcript_text and call_uuid in conversation_logs:
                                logger.info(f"🎤 User: {transcript_text}")
                                conversation_logs[call_uuid].append({
                                    "speaker": "user", 
                                    "text": transcript_text
                                })

                        if response.get("type") == "response.done":
                            for item in response.get("response", {}).get("output", []):
                                if item.get("type") == "message":
                                    last_assistant_item = item.get("id")
                                    for part in item.get("content", []):
                                        if part.get("type") == "audio" and "transcript" in part:
                                            if part["transcript"] and call_uuid in conversation_logs:
                                                conversation_logs[call_uuid].append({
                                                    "speaker": "assistant",
                                                    "text": part["transcript"],
                                                })
                                            logger.info(f"🤖 Assistant: {part['transcript']}")

                        if response.get("type") == "response.audio.delta":
                            try:
                                # OpenAI:lta tuleva audio muLaw 8kHz -> L16 16kHz Vonagelle
                                audio_data = base64.b64decode(response["delta"])
                                # Tässäkin tarvittaisiin kunnollinen resämplöinti
                                audio_b64 = base64.b64encode(audio_data).decode()
                                
                                # Lähetä Vonagelle
                                await websocket.send_text(audio_b64)
                                
                                if response_start_timestamp is None:
                                    response_start_timestamp = latest_media_timestamp

                            except Exception as e:
                                logger.error(f"Error sending audio to Vonage: {e}")
                                break

                        if response.get("type") == "response.audio.done":
                            logger.info("✔️ AI finished audio response")

                        if response.get("type") == "input_audio_buffer.speech_started":
                            logger.info("🗣️ Speech started detected")
                            if last_assistant_item:
                                logger.info(f"Interrupting response id={last_assistant_item}")
                                await handle_speech_started_event()

                except WebSocketDisconnect:
                    logger.info("WebSocket disconnected in send_to_vonage")
                except Exception as e:
                    logger.error(f"Error in send_to_vonage: {e}")
                finally:
                    logger.info("send_to_vonage task ending")

            async def handle_speech_started_event():
                """Truncate AI response when user starts speaking."""
                nonlocal response_start_timestamp, last_assistant_item
                
                if not last_assistant_item or response_start_timestamp is None:
                    return
                    
                elapsed = latest_media_timestamp - response_start_timestamp
                
                if elapsed < 100:
                    return

                try:
                    truncate_event = {
                        "type": "conversation.item.truncate",
                        "item_id": last_assistant_item,
                        "content_index": 0,
                        "audio_end_ms": elapsed,
                    }
                    await openai_ws.send(json.dumps(truncate_event))
                except Exception as e:
                    logger.error(f"Error truncating response: {e}")
                finally:
                    last_assistant_item = None
                    response_start_timestamp = None

            logger.info("Starting async tasks for Vonage WebSocket")
            tasks = [
                asyncio.create_task(receive_from_vonage()),
                asyncio.create_task(send_to_vonage())
            ]
            
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            call_ended = True
            
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        except Exception as e:
            logger.error(f"Error in Vonage WebSocket: {e}")
        finally:
            logger.info("Cleaning up Vonage WebSocket resources")
            
            if openai_ws:
                try:
                    await openai_ws.close()
                except Exception:
                    pass
            
            try:
                await websocket.close()
            except Exception:
                pass

            if call_uuid:
                await save_conversation_log(call_uuid)


async def initialize_session(openai_ws):
    """Initialize OpenAI session for Finnish interview"""
    session_update = {
        "type": "session.update",
        "session": {
            "turn_detection": {
                "type": "server_vad",
            },
            "input_audio_format": "g711_ulaw",  # Tämä pitää ehkä muuttaa L16:ksi
            "output_audio_format": "g711_ulaw", # Tämä pitää ehkä muuttaa L16:ksi
            "voice": VOICE,
            "instructions": SYSTEM_MESSAGE,
            "modalities": ["text", "audio"],
            "temperature": 0.8,
        },
    }
    
    logger.info("Initializing OpenAI session for Vonage integration")
    await openai_ws.send(json.dumps(session_update))

    create_message = {
        "type": "response.create",
        "response": {
            "modalities": ["text", "audio"],
            "prompt": "Start the interview immediately by greeting the interviewee in Finnish and explaining the topic. Remember to speak ONLY Finnish."
        }
    }
    await openai_ws.send(json.dumps(create_message))
    logger.info("Interview started via OpenAI")


async def save_conversation_log(call_uuid):
    """Save conversation log using call_uuid instead of stream_sid"""
    try:
        if call_uuid not in conversation_logs or not conversation_logs[call_uuid]:
            logger.info(f"No conversation log found for call_uuid {call_uuid}")
            return

        conversation_log = conversation_logs.pop(call_uuid)
        
        log_dir = "conversations_log"
        os.makedirs(log_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filepath = os.path.join(log_dir, f"conversation_log_{call_uuid}_{timestamp}.json")
        
        with open(log_filepath, "w", encoding="utf-8") as f:
            json.dump(conversation_log, f, ensure_ascii=False, indent=2)

        dialogue_turns = []
        for speaker, group in groupby(conversation_log, key=lambda x: x["speaker"]):
            texts = [msg["text"] for msg in group]
            dialogue_turns.append({"speaker": speaker, "text": "\n".join(texts)})

        turns_filepath = os.path.join(log_dir, f"conversation_turns_{call_uuid}_{timestamp}.json")
        with open(turns_filepath, "w", encoding="utf-8") as f:
            json.dump(dialogue_turns, f, ensure_ascii=False, indent=2)

        logger.info(f"Vonage conversation log saved: {len(conversation_log)} messages")

    except Exception as e:
        logger.error(f"Error saving Vonage conversation log: {e}")


# Setup routes
setup_vonage_routes(app)


# TODO: Implement database storage
async def store_interview_in_database(dialogue_turns):
    """Store interview data in the database for news generation."""
    # This function should integrate with your existing database
    pass