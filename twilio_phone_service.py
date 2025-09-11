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
from twilio.twiml.voice_response import VoiceResponse, Connect
from twilio.rest import Client
from datetime import datetime

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
    "Keskustelu voi sisältää kysymyksiä, spontaaneja vastauksia, täytesanoja, taukoja ja erikoistermejä. "
    "Kirjoita kaikki sanat täsmällisesti niin kuin ne kuullaan. "
    "Säilytä välimerkit, tauot ja täytesanat. "
    "Jos jokin sana on epäselvä, merkitse se selvästi esimerkiksi '(epäselvä)'."
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

twilio_client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
LOCALTUNNEL_URL = os.getenv("LOCALTUNNEL_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
VOICE = "shimmer"

# Global variable for current phone script
current_phone_script = None
current_article_id = None

LOG_EVENT_TYPES = [
    "error",
    "response.content.done",
    "rate_limits.updated",
    "response.done",
    "input_audio_buffer.committed",
    "input_audio_buffer.speech_stopped",
    "input_audio_buffer.speech_started",
    "session.created",
    "session.updated",
]
SHOW_TIMING_MATH = False

app = FastAPI()

conversation_logs = {}
"""
Map Twilio Media Stream streamSid -> Twilio Call SID, so we can end the
underlying PSTN call when the websocket stream ends.
"""
stream_to_call = {}
"""
Track article_id associations so transcripts are stored against the correct
article, even with concurrent calls.
call_to_article maps callSid -> article_id
stream_to_article maps streamSid -> article_id
"""
call_to_article = {}
stream_to_article = {}


def setup_twilio_routes(app: FastAPI):
    """Setup all Twilio-related routes on the FastAPI app"""

    @app.api_route("/incoming-call", methods=["GET", "POST"])
    async def handle_incoming_call(request: Request):
        try:
            response = VoiceResponse()
            if not LOCALTUNNEL_URL:
                logger.error("Missing LOCALTUNNEL_URL environment variable")
                raise ValueError("Missing the LOCALTUNNEL_URL environment variable.")

            response.say("Yhdistän sinut haastatteluun.", language="fi-FI")

            connect = Connect()
            connect.stream(
                url=f"{LOCALTUNNEL_URL.replace('https://','wss://')}/media-stream"
            )
            response.append(connect)

            logger.info("Incoming call handled, connecting to media stream")
            return HTMLResponse(content=str(response), media_type="application/xml")

        except Exception as e:
            logger.error(f"Error handling incoming call: {e}")
            response = VoiceResponse()
            response.say(
                "Pahoittelemme, puhelun yhdistämisessä tapahtui virhe. Yritä myöhemmin uudelleen.",
                language="fi-FI",
            )
            return HTMLResponse(content=str(response), media_type="application/xml")

    @app.post("/start-interview")
    async def start_interview(request: Request):
        print("\n\n****HAASTATTELU ALKAA!!****")
        try:
            body = await request.json()
            print(f"Received request body: {body}")

            phone_number = body.get("phone_number")
            phone_script_json = body.get("phone_script_json")
            news_article_id = body.get("article_id")

            # Legacy support
            system_prompt = body.get("system_prompt", "")
            language = body.get("language", "fi")
            interview_context = body.get("interview_context", "")

            if not phone_number:
                return JSONResponse(
                    status_code=400, content={"error": "phone_number is required"}
                )

            twilio_phone_number = os.getenv("TWILIO_PHONE_NUMBER")
            if not twilio_phone_number:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "Missing TWILIO_PHONE_NUMBER environment variable"
                    },
                )
            if not LOCALTUNNEL_URL:
                return JSONResponse(
                    status_code=400,
                    content={"error": "Missing LOCALTUNNEL_URL environment variable"},
                )

            # Tallenna phone_script_json globaalisti initialize_session:ia varten
            global current_phone_script, current_article_id
            current_phone_script = phone_script_json
            current_article_id = news_article_id

            print("ÅÅÅÅÅÅÅÅÅÅÅÅÅÅÅÅÅÅ")
            print("current_article_id: ", current_article_id)

            # Debug logging
            if phone_script_json:
                logger.info("📱 phone_script_json received and stored globally")
                logger.info(f"   Voice: {phone_script_json.get('voice', 'not set')}")
                logger.info(
                    f"   Language: {phone_script_json.get('language', 'not set')}"
                )
                logger.info(
                    f"   Instructions length: {len(phone_script_json.get('instructions', ''))}"
                )
            else:
                logger.info("📱 No phone_script_json - using legacy mode")

            call = twilio_client.calls.create(
                to=phone_number,
                from_=twilio_phone_number,
                url=f"{LOCALTUNNEL_URL}/incoming-call",
            )

            logger.info(
                f"Interview call initiated - SID: {call.sid}, To: {phone_number}"
            )
            conversation_logs[call.sid] = []

            # Link this call to the news article so we can persist correctly later
            if news_article_id:
                call_to_article[call.sid] = news_article_id

            return JSONResponse(
                content={
                    "status": "success",
                    "call_sid": call.sid,
                    "message": f"Interview call initiated to {phone_number}",
                    "to_number": phone_number,
                    "from_number": twilio_phone_number,
                    "language": (
                        phone_script_json.get("language", language)
                        if phone_script_json
                        else language
                    ),
                }
            )

        except Exception as e:
            logger.error(f"Error starting interview: {e}")
            return JSONResponse(
                status_code=500,
                content={"error": f"Failed to start interview: {str(e)}"},
            )
        finally:
            # Palauta alkuperäinen tilanne 5 minuutin kuluttua
            async def restore_defaults():
                await asyncio.sleep(300)
                global current_phone_script
                current_phone_script = None
                logger.info("Phone script cleared, back to defaults")

            asyncio.create_task(restore_defaults())

    @app.post("/trigger-call")
    async def trigger_call():
        try:
            twilio_phone_number = os.getenv("TWILIO_PHONE_NUMBER")
            if not twilio_phone_number:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "Missing TWILIO_PHONE_NUMBER environment variable"
                    },
                )

            to_number = os.getenv("WHERE_TO_CALL")
            if not to_number:
                return JSONResponse(
                    status_code=400,
                    content={"error": "Missing WHERE_TO_CALL environment variable"},
                )

            if not LOCALTUNNEL_URL:
                return JSONResponse(
                    status_code=400,
                    content={"error": "Missing LOCALTUNNEL_URL environment variable"},
                )

            call = twilio_client.calls.create(
                to=to_number,
                from_=twilio_phone_number,
                url=f"{LOCALTUNNEL_URL}/incoming-call",
            )

            logger.info(
                f"Default call initiated successfully - SID: {call.sid}, To: {to_number}"
            )
            conversation_logs[call.sid] = []

            return JSONResponse(
                content={
                    "status": "success",
                    "call_sid": call.sid,
                    "message": f"Call initiated to {to_number}",
                    "to_number": to_number,
                    "from_number": twilio_phone_number,
                }
            )

        except Exception as e:
            logger.error(f"Error initiating call: {e}")
            return JSONResponse(
                status_code=500, content={"error": f"Failed to initiate call: {str(e)}"}
            )

    @app.websocket("/media-stream")
    async def handle_media_stream(websocket: WebSocket):
        logger.info("Client connected to media stream")
        await websocket.accept()

        if not OPENAI_API_KEY:
            logger.error("OpenAI API key not configured")
            await websocket.close(code=1008, reason="OpenAI API key not configured")
            return

        openai_ws = None
        stream_sid = None
        latest_media_timestamp = 0
        last_assistant_item = None
        mark_queue = []
        response_start_timestamp_twilio = None
        call_ended = False

        try:
            logger.info("Connecting to OpenAI Realtime API...")
            openai_ws = await websockets.connect(
                "wss://api.openai.com/v1/realtime?model=gpt-4o-mini-realtime-preview-2024-12-17",
                additional_headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "OpenAI-Beta": "realtime=v1",
                },
            )
            logger.info("Successfully connected to OpenAI")

            await initialize_session(openai_ws)

            async def receive_from_twilio():
                nonlocal stream_sid, latest_media_timestamp, call_ended
                logger.info("Starting receive_from_twilio task")
                try:
                    async for message in websocket.iter_text():
                        data = json.loads(message)
                        logger.debug(f"Received Twilio event: {data.get('event')}")

                        if data["event"] == "media":
                            if "timestamp" in data["media"]:
                                latest_media_timestamp = int(data["media"]["timestamp"])

                            # Suoraan kuten Twilio:n esimerkissä - EI konversiota
                            await openai_ws.send(
                                json.dumps(
                                    {
                                        "type": "input_audio_buffer.append",
                                        "audio": data["media"][
                                            "payload"
                                        ],  # Suoraan payload
                                    }
                                )
                            )

                        elif data["event"] == "start":
                            stream_sid = data["start"]["streamSid"]
                            logger.info(f"Incoming stream has started {stream_sid}")
                            response_start_timestamp_twilio = None
                            latest_media_timestamp = 0
                            last_assistant_item = None

                            if stream_sid not in conversation_logs:
                                conversation_logs[stream_sid] = []

                            # Link streamSid -> callSid for proper teardown later
                            call_sid = data["start"].get("callSid")
                            if call_sid:
                                stream_to_call[stream_sid] = call_sid
                                logger.info(
                                    f"Linked streamSid {stream_sid} -> callSid {call_sid}"
                                )
                                # Also link stream to article, via call mapping
                                article_id_for_call = call_to_article.get(call_sid)
                                if article_id_for_call is not None:
                                    stream_to_article[stream_sid] = article_id_for_call
                                    logger.info(
                                        f"Linked streamSid {stream_sid} -> article_id {article_id_for_call}"
                                    )
                            else:
                                logger.warning(
                                    "start event missing callSid – cannot link stream to call"
                                )

                            logger.info(
                                "Stream started, waiting for AI to respond based on initial session config."
                            )

                        elif data["event"] == "stop":
                            logger.info(f"Stream {stream_sid} has stopped")
                            call_ended = True
                            # Katkaise puhelu Twilion REST API:lla
                            # Jos puhelu ei katkea... se jää "päälle" ikuisesti
                            try:
                                call_sid = stream_to_call.get(stream_sid)
                                if call_sid:
                                    twilio_client.calls(call_sid).update(status="completed")
                                    logger.info(f"☎️ Puhelu {call_sid} päätetty Twilion päästä")
                                else:
                                    logger.warning(
                                        f"No callSid found for streamSid {stream_sid}; cannot end call via API"
                                    )
                            except Exception as e:
                                logger.error(f"Error ending call via Twilio API: {e}")
                            finally:
                                # Cleanup mapping for this stream
                                cs = stream_to_call.pop(stream_sid, None)
                                if cs:
                                    call_to_article.pop(cs, None)
                                stream_to_article.pop(stream_sid, None)
                            break

                        elif data["event"] == "mark" and mark_queue:
                            mark_queue.pop(0)

                except WebSocketDisconnect:
                    logger.info("Twilio WebSocket disconnected")
                    if not call_ended:
                        call_ended = True
                        # Safety: end the PSTN call if we still know the callSid
                        try:
                            call_sid = stream_to_call.get(stream_sid)
                            if call_sid:
                                twilio_client.calls(call_sid).update(status="completed")
                                logger.info(
                                    f"☎️ Puhelu {call_sid} päätetty Twilion päästä (WS disconnect)"
                                )
                            else:
                                logger.warning(
                                    f"No callSid mapping for streamSid {stream_sid} on disconnect"
                                )
                        except Exception as e:
                            logger.error(
                                f"Error ending call via Twilio API on disconnect: {e}"
                            )
                        finally:
                            # Clean mapping regardless
                            cs = stream_to_call.pop(stream_sid, None)
                            if cs:
                                call_to_article.pop(cs, None)
                            stream_to_article.pop(stream_sid, None)
                except Exception as e:
                    logger.error(f"Error in receive_from_twilio: {e}")
                    call_ended = True
                finally:
                    logger.info("receive_from_twilio task ending")

            async def send_to_twilio():
                nonlocal stream_sid, last_assistant_item, response_start_timestamp_twilio, call_ended
                logger.info("Starting send_to_twilio task")
                try:
                    async for openai_message in openai_ws:
                        if call_ended:
                            logger.info("Call has ended, stopping send_to_twilio")
                            break

                        response = json.loads(openai_message)

                        if response.get("type") == "session.created":
                            logger.info("OpenAI session created successfully")
                            logger.info(
                                f"Session details: {json.dumps(response.get('session', {}), indent=2)}"
                            )

                        if response.get("type") == "session.updated":
                            logger.info("🎉 Session updated successfully!")
                            logger.info(
                                f"Updated session: {json.dumps(response.get('session', {}), indent=2)}"
                            )
                            logger.info(
                                "📤 Initial response.create sent after session.updated"
                            )

                        if response.get("type") == "error":
                            error_code = response.get("error", {}).get("code")
                            if (
                                error_code == "invalid_value"
                                and "already shorter than"
                                in response.get("error", {}).get("message", "")
                            ):
                                # Audio truncation error - ei kriittinen
                                logger.warning(
                                    f"Audio truncation timing error (non-critical): {response}"
                                )
                            else:
                                # Muut virheet
                                logger.error(f"OpenAI error: {response}")
                            continue

                        # KÄYTTÄJÄN TRANSCRIPTION KÄSITTELY - PALAUTETTU
                        if (
                            response.get("type")
                            == "conversation.item.input_audio_transcription.completed"
                        ):
                            transcript_text = response.get("transcript", "").strip()
                            if transcript_text and stream_sid in conversation_logs:
                                logger.info(f"🎤 User: {transcript_text}")
                                if (
                                    not conversation_logs[stream_sid]
                                    or conversation_logs[stream_sid][-1].get("text")
                                    != transcript_text
                                ):
                                    conversation_logs[stream_sid].append(
                                        {"speaker": "user", "text": transcript_text}
                                    )

                        # KORJATTU: response.done käsittely oikeassa paikassa
                        if response.get("type") == "response.done":
                            if SHOW_TIMING_MATH:
                                print("[DEBUG] response.done received")

                            for item in response.get("response", {}).get("output", []):
                                if item.get("type") == "message":
                                    last_assistant_item = item.get("id")
                                    for part in item.get("content", []):
                                        if (
                                            part.get("type") == "audio"
                                            and "transcript" in part
                                        ):
                                            transcript = part["transcript"]

                                            # TUNNISTA LOPETUSSANAT
                                            end_phrases = [
                                                "kiitos haastattelusta",
                                                "hyvää päivänjatkoa",
                                                "haastattelu päättyi kiitos",
                                                "nämä olivat kaikki kysymykset",
                                            ]

                                            if any(
                                                phrase in transcript.lower()
                                                for phrase in end_phrases
                                            ):
                                                logger.info(
                                                    f"🔚 Detected interview end phrase in: {transcript}"
                                                )

                                                # Anna AI:lle hetki sanoa loppuun (2 sekuntia)
                                                await asyncio.sleep(2)

                                                call_ended = True
                                                logger.info(
                                                    "📞 Ending call after interview completion"
                                                )

                                                try:
                                                    await websocket.close()
                                                    await openai_ws.close()
                                                    logger.info(
                                                        "✅ Call ended successfully"
                                                    )
                                                except Exception as e:
                                                    logger.warning(
                                                        f"Error closing connections: {e}"
                                                    )

                                                return

                                            # Tavallinen logging - VAIN AI:n vastaukset
                                            if (
                                                transcript
                                                and stream_sid in conversation_logs
                                            ):
                                                conversation_logs[stream_sid].append(
                                                    {
                                                        "speaker": "assistant",
                                                        "text": transcript,
                                                    }
                                                )
                                            logger.info(f"🤖 Assistant: {transcript}")

                        if (
                            response.get("type") == "response.audio.delta"
                            and stream_sid
                        ):
                            try:
                                # THIS IS USED IN TWILIO EXAMPLE... EVEN ITS BIT WEIRD, LETS USE THIS
                                audio_payload = base64.b64encode(
                                    base64.b64decode(response["delta"])
                                ).decode("utf-8")

                                await websocket.send_json(
                                    {
                                        "event": "media",
                                        "streamSid": stream_sid,
                                        "media": {"payload": audio_payload},
                                    }
                                )

                                if response_start_timestamp_twilio is None:
                                    response_start_timestamp_twilio = (
                                        latest_media_timestamp
                                    )
                                    if SHOW_TIMING_MATH:
                                        print(
                                            f"[DEBUG] set response_start_timestamp={response_start_timestamp_twilio}ms"
                                        )
                                await send_mark(websocket, stream_sid)
                            except Exception as e:
                                logger.error(f"Error sending audio to Twilio: {e}")
                                break

                        if response.get("type") == "response.audio.done":
                            logger.info("✔️ AI finished audio response")
                            await websocket.send_json({"event": "ai_response_done"})

                        if response.get("type") == "input_audio_buffer.speech_started":
                            logger.info("🗣️ Speech started detected")
                            if last_assistant_item:
                                logger.info(
                                    f"Interrupting response id={last_assistant_item}"
                                )
                                await handle_speech_started_event()

                except WebSocketDisconnect:
                    logger.info("WebSocket disconnected in send_to_twilio")
                except Exception as e:
                    logger.error(f"Error in send_to_twilio: {e}")
                finally:
                    logger.info("send_to_twilio task ending")

            async def send_mark(connection, stream_sid_local):
                """Send mark events to Twilio to indicate audio chunks have been sent."""
                if stream_sid_local:
                    mark_event = {
                        "event": "mark",
                        "streamSid": stream_sid_local,
                        "mark": {"name": "responsePart"},
                    }
                    await connection.send_json(mark_event)
                    mark_queue.append("responsePart")
                    if SHOW_TIMING_MATH:
                        print("[DEBUG] sent mark=responsePart")

            async def handle_speech_started_event():
                """Truncate AI response when user starts speaking - with IMPROVED timing."""
                nonlocal response_start_timestamp_twilio, last_assistant_item, stream_sid

                if not last_assistant_item or response_start_timestamp_twilio is None:
                    logger.info("No active response to interrupt")
                    return

                elapsed = latest_media_timestamp - response_start_timestamp_twilio

                #  Anna AI:lle aikaa sanoa asiansa loppuun
                if elapsed < 3000:  # NOSTETTU 500ms → 3000ms (3 sekuntia)
                    logger.info(
                        f"Too early to interrupt AI ({elapsed}ms) - letting it finish"
                    )
                    return

                if SHOW_TIMING_MATH:
                    print(f"[DEBUG] truncating at {elapsed}ms")

                try:
                    truncate_event = {
                        "type": "conversation.item.truncate",
                        "item_id": last_assistant_item,
                        "content_index": 0,
                        "audio_end_ms": elapsed,
                    }
                    await openai_ws.send(json.dumps(truncate_event))
                    await websocket.send_json(
                        {"event": "clear", "streamSid": stream_sid}
                    )
                    mark_queue.clear()
                    logger.info(f"✂️ Truncated audio at {elapsed}ms")

                except Exception as e:
                    logger.warning(f"Audio truncation failed (non-critical): {e}")
                    mark_queue.clear()

                finally:
                    last_assistant_item = None
                    response_start_timestamp_twilio = None

            logger.info("Starting async tasks for media stream")
            tasks = [
                asyncio.create_task(receive_from_twilio()),
                asyncio.create_task(send_to_twilio()),
            ]

            done, pending = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED
            )
            logger.info(f"Task completed. Done: {len(done)}, Pending: {len(pending)}")

            call_ended = True

            for task in pending:
                logger.info(f"Cancelling pending task")
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    logger.info(f"Task cancelled successfully")

            logger.info("Media stream tasks completed")

        except Exception as e:
            logger.error(f"Error in media stream WebSocket: {e}")
        finally:
            logger.info("Cleaning up media stream resources")

            if openai_ws:
                try:
                    await openai_ws.close()
                    logger.info("OpenAI WebSocket closed")
                except Exception as e:
                    logger.error(f"Error closing OpenAI WebSocket: {e}")

            try:
                await websocket.close()
                logger.info("Twilio WebSocket closed")
            except Exception as e:
                logger.error(f"Error closing Twilio WebSocket: {e}")

            if stream_sid:
                await save_conversation_log(stream_sid)

            logger.info("Media stream handler completed")


async def initialize_session(openai_ws):
    """Initialize OpenAI session - Twilio:n mallin mukaan"""
    global current_phone_script

    logger.info("📋 Building session configuration...")
    logger.info(f"current_phone_script status: {current_phone_script is not None}")

    # ODOTA 0.25s ennen session.update:a (kuten Twilio:n esimerkissä)
    await asyncio.sleep(0.25)
    logger.info("⏳ Sending session update after 250ms delay...")

    # Käytä phone_script_json jos saatavilla
    if current_phone_script:
        logger.info("🎯 USING PHONE_SCRIPT_JSON CONFIGURATION!")
        instructions = current_phone_script.get("instructions")
        requested_voice = current_phone_script.get("voice", VOICE)

        # Validoi voice
        supported_voices = [
            "alloy",
            "ash",
            "ballad",
            "coral",
            "echo",
            "sage",
            "shimmer",
            "verse",
        ]
        if requested_voice in supported_voices:
            voice = requested_voice
        else:
            voice = "coral" if current_phone_script.get("language") == "fi" else "alloy"
            logger.warning(
                f"Voice '{requested_voice}' not supported, using '{voice}' instead"
            )

        temperature = current_phone_script.get("temperature", 0.8)
        language = current_phone_script.get("language", "fi")

        clean_script = current_phone_script.copy()
        base_instructions = clean_script.pop("instructions")

        instructions = (
            f"{base_instructions}\n\n"
            "TÄRKEÄ: Kun olet kysynyt kaikki kysymykset ja kiittänyt haastattelusta, "
            "sano selkeästi 'HAASTATTELU PÄÄTTYI KIITOS' ja lopeta puhuminen.\n\n"
            f"{json.dumps(clean_script, ensure_ascii=False, indent=2)}"
        )

    else:
        logger.info("🔄 Using default configuration")
        instructions = SYSTEM_MESSAGE
        voice = VOICE
        temperature = 0.8
        language = "fi"

    # PARANNELTU: session update paremmilla keskeytyksien asetuksilla + transcription
    session_update = {
        "type": "session.update",
        "session": {
            "turn_detection": {
                "type": "server_vad",
                "threshold": 0.75,  # NOSTETTU 0.6 → 0.75 (vähemmän herkkä)
                "silence_duration_ms": 1200,  # NOSTETTU 800 → 1500ms (pidempi odotus)
                "create_response": True,
                "interrupt_response": True,
            },
            "input_audio_format": "g711_ulaw",
            "output_audio_format": "g711_ulaw",
            "voice": voice,
            "instructions": instructions,
            "modalities": ["text", "audio"],
            "temperature": temperature,
            # LISÄTTY: Transcription käyttäjän äänelle
            "input_audio_transcription": {
                "model": "whisper-1",
                #"language": language,
                "language": "fi",
                "prompt": TRANSCRIPTION_PROMPT,
            },
        },
    }

    print("TÄÄ KIINNOSTAA!")
    print(session_update)

    try:
        logger.info("📤 Sending session update (Twilio style)...")
        logger.info(f"Voice: {voice}, Temperature: {temperature}")
        logger.info(f"Instructions: {instructions[:100]}...")

        await openai_ws.send(json.dumps(session_update))
        logger.info("✅ Session update sent successfully")

    except Exception as e:
        logger.error(f"❌ Failed to send session update: {e}")
        raise


async def save_conversation_log(stream_sid):
    """Save conversation log to files and UPDATE database using article_id."""
    try:
        if stream_sid not in conversation_logs or not conversation_logs[stream_sid]:
            logger.info(
                f"No conversation log found for stream_sid {stream_sid}, nothing to save."
            )
            return

        conversation_log = conversation_logs.pop(stream_sid)

        # Tallenna tiedostoihin (backup)
        log_dir = "conversations_log"
        os.makedirs(log_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filepath = os.path.join(
            log_dir, f"conversation_log_{stream_sid}_{timestamp}.json"
        )

        with open(log_filepath, "w", encoding="utf-8") as f:
            json.dump(conversation_log, f, ensure_ascii=False, indent=2)

        # Luo dialogue_turns
        dialogue_turns = []
        for speaker, group in groupby(conversation_log, key=lambda x: x["speaker"]):
            texts = [msg["text"] for msg in group]
            dialogue_turns.append({"speaker": speaker, "text": "\n".join(texts)})

        turns_filepath = os.path.join(
            log_dir, f"conversation_turns_{stream_sid}_{timestamp}.json"
        )
        with open(turns_filepath, "w", encoding="utf-8") as f:
            json.dump(dialogue_turns, f, ensure_ascii=False, indent=2)

        # PÄIVITÄ tietokanta käyttäen article_id:tä
        # Prefer stream-specific mapping; fall back to global (single-call case)
        global current_article_id
        article_id = stream_to_article.pop(stream_sid, None)
        if article_id is None:
            article_id = current_article_id  # fallback for legacy/test flows

        if article_id is not None:
            # THIS WILL SAVE INTERVIEW ANSWERS TO DB
            interview_id = await update_interview_by_article_id(
                article_id, dialogue_turns
            )

            if interview_id:
                logger.info(
                    f"✅ Interview {interview_id} updated for article {article_id}"
                )
            else:
                logger.info(f"ℹ️ No initiated interview found for article: {article_id}")
        else:
            logger.info("ℹ️ No article_id available - this is likely a test call")

        logger.info(
            f"Conversation log for stream_sid {stream_sid} saved successfully ({len(conversation_log)} messages)"
        )
        logger.info(f"Files saved: {log_filepath} and {turns_filepath}")

    except Exception as e:
        logger.error(f"Error saving conversation log for stream_sid {stream_sid}: {e}")


# WE NEED TO UPDATE INTERVIEW TO THE DATABASE
# WE ARE USING ARTICLE_ID (what we get from "start_interview(request: Request)") TO IDENTIFY THE INTERVIEW and correct ARTICLE
async def update_interview_by_article_id(article_id, dialogue_turns):
    """Update existing phone interview with transcript using article_id."""
    try:
        import asyncpg

        # Database connection
        conn = await asyncpg.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", 5432),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME", "newsroom"),
        )

        # Prepare transcript data
        transcript_json = {
            "dialogue_turns": dialogue_turns,
            "call_metadata": {
                "completed_at": datetime.now().isoformat(),
                "total_turns": len(dialogue_turns),
                "total_assistant_messages": len(
                    [t for t in dialogue_turns if t.get("speaker") == "assistant"]
                ),
                "total_user_messages": len(
                    [t for t in dialogue_turns if t.get("speaker") == "user"]
                ),
            },
        }

        # Etsi viimeisin "initiated" status interview tälle article_id:lle
        update_query = """
            UPDATE phone_interview 
            SET 
                transcript_json = $1,
                status = $2
            WHERE news_article_id = $3 
            RETURNING id
        """

        interview_id = await conn.fetchval(
            update_query,
            json.dumps(transcript_json),  # $1 - transcript as JSONB
            "completed",  # $2 - new status
            article_id,  # $3 - article_id (news_article_id kolumnissa)
        )

        if interview_id:
            # Päivitä myös phone_interview_attempt jos sellainen on
            await conn.execute(
                """
                UPDATE phone_interview_attempt 
                SET ended_at = NOW(), status = $1
                WHERE phone_interview_id = $2
                """,
                "completed",
                interview_id,
            )

            logger.info(
                f"📊 Updated interview ID {interview_id} for article {article_id} with transcript ({len(dialogue_turns)} turns)"
            )
        else:
            logger.warning(
                f"⚠️ No initiated phone_interview found for article: {article_id}"
            )
            logger.info(
                "This might be a test call or the interview was already completed"
            )

        await conn.close()
        return interview_id

    except Exception as e:
        logger.error(f"❌ Failed to update interview in database: {e}")
        return None
