#!/usr/bin/env python3
"""
Yksinkertainen Vonage Voice API testi
Tekee pelkän puhelun ilman WebSocket:ia tai muita hömppöjä
"""

import os
from dotenv import load_dotenv
from vonage import Vonage, Auth
from vonage_voice import CreateCallRequest

# Lataa .env tiedosto
load_dotenv()

# Aseta ympäristömuuttujat
VONAGE_APPLICATION_ID = os.getenv("VONAGE_APPLICATION_ID")
VONAGE_PRIVATE_KEY_PATH = os.getenv("VONAGE_PRIVATE_KEY")  # Polku .key tiedostoon
VONAGE_NUMBER = os.getenv("VONAGE_NUMBER")  # Oma numero
TO_NUMBER = os.getenv("WHERE_TO_CALL_VONAGE")  # Mihin soitetaan

def load_private_key():
    """Lataa private key tiedostosta"""
    if VONAGE_PRIVATE_KEY_PATH and os.path.exists(VONAGE_PRIVATE_KEY_PATH):
        with open(VONAGE_PRIVATE_KEY_PATH, 'r') as f:
            return f.read()
    else:
        print(f"Private key tiedostoa ei löydy: {VONAGE_PRIVATE_KEY_PATH}")
        return None

def make_simple_call():
    """Tee yksinkertainen puhelu joka vain sanoo tervehdyksen"""
    
    # Lataa private key
    private_key_content = load_private_key()
    if not private_key_content:
        return False
    
    # Luo Vonage client
    auth = Auth(
        application_id=VONAGE_APPLICATION_ID,
        private_key=private_key_content
    )
    vonage_client = Vonage(auth=auth)
    
    # Yksinkertainen NCCO - vain tervehdys
    simple_ncco = [
        {
            "action": "talk",
            "text": "Hei! Tämä on testi puhelu Vonage Voice API:sta. Kiitos ja hei hei!",
            "language": "fi-FI"
        }
    ]
    
    # Puhelun parametrit - kokeile omaa numeroa (ilman + merkkiä)
    call_params = {
        "to": [{"type": "phone", "number": TO_NUMBER}],
        "from_": {"type": "phone", "number": VONAGE_NUMBER},  # Ilman + merkkiä
        "ncco": simple_ncco
    }
    
    print(f"Soitetaan numeroon: {TO_NUMBER}")
    print(f"Soitetaan numerosta: +{VONAGE_NUMBER}")
    print(f"Application ID: {VONAGE_APPLICATION_ID}")
    print(f"NCCO: {simple_ncco}")
    
    try:
        # Luo puhelu
        call_request = CreateCallRequest(**call_params)
        print(f"Call request luotu: {call_request}")
        
        # Tee puhelu
        response = vonage_client.voice.create_call(call_request)
        
        print(f"Puhelu onnistui!")
        print(f"Call UUID: {response.uuid}")
        print(f"Status: {response.status}")
        
        return True
        
    except Exception as e:
        print(f"Virhe puhelussa: {e}")
        return False

if __name__ == "__main__":
    print("=== Vonage Voice API Yksinkertainen Testi ===")
    
    # Tarkista ympäristömuuttujat
    if not VONAGE_APPLICATION_ID:
        print("VIRHE: VONAGE_APPLICATION_ID puuttuu")
        exit(1)
    
    if not VONAGE_PRIVATE_KEY_PATH:
        print("VIRHE: VONAGE_PRIVATE_KEY puuttuu")
        exit(1)
        
    if not VONAGE_NUMBER:
        print("VIRHE: VONAGE_NUMBER puuttuu")
        exit(1)
        
    if not TO_NUMBER:
        print("VIRHE: WHERE_TO_CALL_VONAGE puuttuu")
        exit(1)
    
    # Tee puhelu
    success = make_simple_call()
    
    if success:
        print("\n✅ Testi onnistui!")
    else:
        print("\n❌ Testi epäonnistui!")