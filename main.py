import threading
from flask import Flask
import time
import os
import logging
import requests
import asyncio
from playwright.sync_api import sync_playwright
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ===========================================
# CONFIGURACIÓN
# ===========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8400265046:AAHA_qjtya3Gf2kqB-16ODGhKKFeIsjN72E")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "-1003744855469") 
URL = "https://outlook.office365.com/book/Atencinalpblico@cancilleria.gov.co/?ismsaljsauthenabled=true"
NOMBRE_SERVICIO = os.environ.get("SERVICIO", "Cédula Primera vez")
REVISAR_CADA = int(os.environ.get("INTERVALO", 290))
PUERTO = int(os.environ.get("PORT", 8080))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ===========================================
# SERVIDOR WEB
# ===========================================
app = Flask(__name__)
ultima_verificacion = "Nunca"
ultimo_estado = "Iniciando..."
citas_encontradas_total = 0

@app.route('/')
def health(): 
    return f"Bot Activo. Última revisión: {ultima_verificacion}. Estado: {ultimo_estado}", 200

def enviar_telegram(mensaje):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "HTML"}, timeout=10)
        logging.info("✅ Mensaje enviado a Telegram")
    except Exception as e:
        logging.error(f"Error Telegram: {e}")

# ===========================================
# LÓGICA DE BÚSQUEDA CON PLAYWRIGHT
# ===========================================
def buscar_citas():
    global ultima_verificacion, ultimo_estado, citas_encontradas_total
    ultima_verificacion = time.strftime('%Y-%m-%d %H:%M:%S')
    
    try:
        with sync_playwright() as p:
            logging.info(f"🔍 Iniciando búsqueda para: {NOMBRE_SERVICIO}")
            browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
            page = browser.new_page()
            page.goto(URL, wait_until="networkidle", timeout=60000)
            time.sleep(8)
            
            # ========== 1. SELECCIONAR SERVICIO ==========
            try:
                try:
                    boton_mostrar = page.locator("//button[contains(text(), 'Mostrar más servicios')]")
                    if boton_mostrar.count() > 0:
                        boton_mostrar.click()
                        logging.info("✅ Click en 'Mostrar más servicios'")
                        time.sleep(3)
                except Exception:
                    logging.info("No se encontró botón 'Mostrar más servicios'")
                
                servicios = page.locator("div.XNuah").all()
                servicio_encontrado = False
                
                for servicio in servicios:
                    texto_servicio = servicio.inner_text().strip()
                    logging.info(f"Servicio encontrado: '{texto_servicio}'")
                    
                    if texto_servicio == NOMBRE_SERVICIO:
                        logging.info(f"✅ Servicio exacto encontrado: '{texto_servicio}'")
                        radio = servicio.locator("xpath=./ancestor::li//input[@type='radio']")
                        radio.click(force=True)
                        servicio_encontrado = True
                        logging.info(f"✅ Servicio seleccionado: {NOMBRE_SERVICIO}")
                        break
                
                if not servicio_encontrado:
                    for servicio in servicios:
                        texto_servicio = servicio.inner_text().strip()
                        if NOMBRE_SERVICIO.lower() in texto_servicio.lower():
                            logging.info(f"✅ Servicio parcial encontrado: '{texto_servicio}'")
                            radio = servicio.locator("xpath=./ancestor::li//input[@type='radio']")
                            radio.click(force=True)
                            servicio_encontrado = True
                            logging.info(f"✅ Servicio seleccionado (parcial): {texto_servicio}")
                            break
                
                if not servicio_encontrado:
                    logging.error(f"❌ No se encontró el servicio: {NOMBRE_SERVICIO}")
                    ultimo_estado = f"Servicio '{NOMBRE_SERVICIO}' no encontrado"
                    browser.close()
                    return
                    
            except Exception as e:
                logging.error(f"Error seleccionando servicio: {e}")
                ultimo_estado = f"Error seleccionando servicio: {str(e)[:50]}"
                browser.close()
                return
            
            time.sleep(5)
            
            # ========== 2. BUSCAR DÍAS DISPONIBLES ==========
            dias = page.locator("div.omApa[data-value]").all()
            logging.info(f"Total días encontrados en calendario: {len(dias)}")
            
            dias_disponibles = []
            
            for dia in dias:
                try:
                    numero = dia.inner_text().strip()
                    if numero and numero.isdigit():
                        aria_disabled = dia.get_attribute("aria-disabled")
                        if aria_disabled != "true":
                            dias_disponibles.append(numero)
                            logging.info(f"📆 Día disponible encontrado: {numero}")
                except Exception:
                    continue
            
            if dias_disponibles:
                dias_ordenados = sorted(list(set(dias_disponibles)), key=int)
                citas_encontradas_total += 1
                ultimo_estado = f"✅ {len(dias_ordenados)} días con citas"
                
                mensaje = f"<b>🔔 ¡CITAS DISPONIBLES!</b>\n\n"
                mensaje += f"<b>Servicio:</b> {NOMBRE_SERVICIO}\n"
                mensaje += f"<b>📅 Fecha:</b> {ultima_verificacion}\n"
                mensaje += f"<b>✅ Días con citas:</b> {len(dias_ordenados)}\n"
                for d in dias_ordenados:
                    mensaje += f"    📆 Día {d}\n"
                mensaje += f"\n🔗 <a href='{URL}'>Reservar ahora</a>"
                
                enviar_telegram(mensaje)
                logging.info(f"🎉 CITAS ENCONTRADAS: {dias_ordenados}")
            else:
                ultimo_estado = "❌ Sin citas disponibles"
                logging.info("❌ No hay citas disponibles en este momento")
                
            browser.close()
            
    except Exception as e:
        ultimo_estado = f"⚠ Error: {str(e)[:100]}"
        logging.error(f"Error en búsqueda: {e}")

# ===========================================
# TELEGRAM BOT
# ===========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = (
        f"🤖 <b>Bot de Citas - Estado</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📱 <b>Servicio:</b> {NOMBRE_SERVICIO}\n"
        f"🕒 <b>Última revisión:</b> {ultima_verificacion}\n"
        f"📊 <b>Estado:</b> {ultimo_estado}\n"
        f"🔄 <b>Intervalo:</b> {REVISAR_CADA} segundos"
    )
    await update.message.reply_text(status_msg, parse_mode="HTML")

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Buscando citas... por favor espera.")
    threading.Thread(target=buscar_citas, daemon=True).start()

async def run_tg():
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("check", check_command))
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    while True:
        await asyncio.sleep(3600)

def loop_busqueda():
    time.sleep(15)
    enviar_telegram(f"🚀 Bot Iniciado\n📱 Servicio: {NOMBRE_SERVICIO}\n🔄 Intervalo: {REVISAR_CADA}s")
    while True:
        try:
            buscar_citas()
        except Exception as e:
            logging.error(f"Error en loop: {e}")
        time.sleep(REVISAR_CADA)

# ===========================================
# MAIN
# ===========================================
if __name__ == "__main__":
    logging.info("="*50)
    logging.info("🤖 BOT DE CITAS INICIADO")
    logging.info(f"📱 Servicio: {NOMBRE_SERVICIO}")
    logging.info(f"🔄 Revisando cada {REVISAR_CADA} segundos")
    logging.info("="*50)
    
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=PUERTO, debug=False, use_reloader=False), daemon=True).start()
    threading.Thread(target=lambda: asyncio.run(run_tg()), daemon=True).start()
    loop_busqueda()
