import os
import telebot
from google.cloud import dialogflow_v2 as dialogflow
from google.oauth2 import service_account
from pymongo import MongoClient
from datetime import datetime
import streamlit as st

# ==================== 1. CONFIGURACIÓN DESDE SECRETS ====================
# En la nube de Streamlit jalamos todo de st.secrets para máxima seguridad
TOKEN_TELEGRAM = st.secrets["TOKEN_TELEGRAM"]
PROJECT_ID = st.secrets["PROJECT_ID"]
MONGO_URI = st.secrets["MONGO_URI"]

# Autenticación de Google Cloud usando el diccionario cargado en Secrets
creds_dict = st.secrets["GOOGLE_CREDENTIALS"]
credentials = service_account.Credentials.from_service_account_info(creds_dict)

# Configuración básica en la interfaz de Streamlit para saber que el contenedor corre bien
st.title("🚀 Panel del Bot de Cayena")
st.write("El bot de Telegram está corriendo en segundo plano...")

# Inicializamos el bot de Telegram
bot = telebot.TeleBot(TOKEN_TELEGRAM)

# Memoria temporal para guardar los datos mientras el usuario responde
memoria_reservas = {}

@st.cache_resource
def init_connection():
    """Mantiene una sola conexión a MongoDB compartida"""
    return MongoClient(MONGO_URI)

try:
    cliente_mongo = init_connection()
    db = cliente_mongo['restaurante_cayena']
    coleccion = db['reservaciones']
    st.success("✅ Conexión a MongoDB Atlas: Exitosa")
except Exception as e:
    st.error(f"❌ Error al conectar MongoDB: {e}")

# ==================== 2. LÓGICA DE TELEGRAM ====================
@bot.message_handler(func=lambda message: True)
def chat_principal(message):
    chat_id = str(message.chat.id)
    
    # Inicializamos la mochila para el usuario si es nuevo
    if chat_id not in memoria_reservas:
        memoria_reservas[chat_id] = {"fecha": "No capturada", "hora": "No capturada", "personas": "1"}

    # Conexión con Dialogflow usando las credenciales seguras de Streamlit
    session_client = dialogflow.SessionsClient(credentials=credentials)
    session = session_client.session_path(PROJECT_ID, chat_id)
    text_input = dialogflow.TextInput(text=message.text, language_code='es')
    query_input = dialogflow.QueryInput(text=text_input)
    response = session_client.detect_intent(request={"session": session, "query_input": query_input})
    
    if response:
        res_query = response.query_result
        bot.reply_to(message, res_query.fulfillment_text)
        
        params = dict(res_query.parameters)

        # --- RECOLECCIÓN Y LIMPIEZA INICIAL ---
        def limpiar_basico(dato):
            if not dato: return None
            return str(dato).replace('[', '').replace(']', '').replace("'", "").strip()

        # Guardamos lo que vaya llegando en la mochila
        if params.get('date1'): 
            memoria_reservas[chat_id]["fecha"] = limpiar_basico(params.get('date1'))
        if params.get('time'): 
            memoria_reservas[chat_id]["hora"] = limpiar_basico(params.get('time'))
        if params.get('number'): 
            memoria_reservas[chat_id]["personas"] = limpiar_basico(params.get('number'))

        # --- DETECCIÓN DE CIERRE (Cuando llega el nombre) ---
        nombre_detectado = params.get('any') or params.get('any1')
        
        if nombre_detectado:
            # --- FORMATEO FINAL PARA ORDENAR LOS DATOS ---
            f_raw = memoria_reservas[chat_id]["fecha"]
            h_raw = memoria_reservas[chat_id]["hora"]
            
            # Limpiar fecha
            fecha_final = f_raw.split('T')[0] if 'T' in f_raw else f_raw
            
            # Limpiar hora
            hora_final = h_raw
            if 'T' in h_raw:
                hora_final = h_raw.split('T')[1].split('-')[0].split('+')[0]

            nueva_reserva = {
                "cliente": str(nombre_detectado).title(),
                "fecha_reserva": fecha_final,
                "hora_reserva": hora_final,
                "comensales": memoria_reservas[chat_id]["personas"],
                "chat_id": chat_id,
                "fecha_registro": datetime.now().strftime("%d/%m/%Y %H:%M")
            }
            
            try:
                # Guardamos en la base de datos
                coleccion.insert_one(nueva_reserva)
                print("-" * 40)
                print(f"⭐ ¡RESERVA ORGANIZADA EN MONGO!")
                print(f"Detalle: {nueva_reserva}")
                print("-" * 40)
                
                # Reseteamos la mochila para futuras reservas
                memoria_reservas[chat_id] = {"fecha": "No capturada", "hora": "No capturada", "personas": "1"}
            except Exception as e:
                print(f"❌ Error al insertar en Atlas: {e}")

# Ejecución continua dentro de Streamlit
if __name__ == "__main__":
    bot.infinity_polling()