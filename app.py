import streamlit as st
import json
import uuid
import qrcode
import base64
from io import BytesIO
from datetime import datetime
import urllib.parse
import requests
import os
import pdfkit
from supabase import create_client, Client
import textwrap

# Cargar los datos desde los archivos JSON
with open('Tarifas_Base.json', 'r') as f:
    tarifas_base = json.load(f)

with open('Zonas_Localidades.json', 'r') as f:
    zonas_localidades = json.load(f)

with open('Parametros.json', 'r') as f:
    parametros = json.load(f)

with open('Depositos.json', 'r') as f:
    depositos_data = json.load(f)
    lista_depositos = depositos_data["Lista_de_Depositos"]

# Inicializar cliente Supabase
url = st.secrets["supabase"]["url"]
access_key = st.secrets["supabase"]["access_key"]
supabase: Client = create_client(url, access_key)

# Función para cargar y guardar caché de distancias
def cargar_cache_distancias():
    try:
        with open('distancias_cache.json', 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def guardar_cache_distancias(cache):
    with open('distancias_cache.json', 'w') as f:
        json.dump(cache, f)

# Función para generar QR en base64
def generar_qr(data):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=4,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode()

# Función para calcular la distancia usando OpenRouteService con caché
def calcular_distancia(origen_lat, origen_lon, destino_lat, destino_lon):
    cache = cargar_cache_distancias()
    clave = f"{origen_lat},{origen_lon},{destino_lat},{destino_lon}"
    
    if clave in cache:
        return cache[clave]
    
    url = "https://api.openrouteservice.org/v2/directions/driving-car"
    headers = {
        "Accept": "application/json, application/geo+json, application/gpx+xml, img/png; charset=utf-8",
        "Authorization": f"Bearer {st.secrets['openrouteservice']['api_key']}"
    }
    params = {
        "start": f"{origen_lon},{origen_lat}",
        "end": f"{destino_lon},{destino_lat}"
    }
    
    try:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            data = response.json()
            distancia_km = data['features'][0]['properties']['segments'][0]['distance'] / 1000
            cache[clave] = round(distancia_km, 2)
            guardar_cache_distancias(cache)
            return cache[clave]
        else:
            st.error(f"Error API: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        st.error(f"Error de conexión: {str(e)}")
        return None

# Función para resetear el formulario
def resetear_formulario():
    keys_to_reset = [
        'deposito_seleccionado', 'zona_seleccionada', 'localidad_seleccionada',
        'peso_seleccionado', 'incluir_iva', 'desea_facturar',
        'cantidad', 'costo_final'
    ]
    for key in keys_to_reset:
        if key in st.session_state:
            del st.session_state[key]

# Función para calcular el costo final
def calcular_costo_final(peso, distancia, localidad, incluir_iva, desea_facturar, cantidad, valor_mercaderia=None):
    if not all([peso, distancia, localidad]):
        return None
    
    tarifa_base = next(
        (item['Tarifa_Base'] for item in tarifas_base 
         if item['Descripcion'] == peso and item['ID_Zona'] == st.session_state.zona_seleccionada),
        None
    )
    
    recargo_localidad = next(
        (item['Recargo_Localidad'] for item in zonas_localidades 
         if item['Localidad'].strip() == localidad.strip()), 0
    )
    
    consumo_combustible = parametros[0]['Consumo_Combustible_Litros_Km']
    precio_combustible = parametros[0]['Precio_Combustible']
    costo_km = parametros[0]['Costo_Km']
    margen_ganancia = parametros[0]['Margen_Ganancia']
    
    costo_base = (
        tarifa_base 
        # + 
        # (consumo_combustible * distancia * precio_combustible) + 
        # costo_km + 
        # recargo_localidad
    ) * (1 + 
         margen_ganancia)
    
    if incluir_iva:
        costo_base *= 1.21

    # Aplicar cantidad solo si NO es Bulto Mínimo
    if peso !="BULTO MINIMO (MAXIMO 20 KG)":
        costo_base *= cantidad

    seguro_carga = (valor_mercaderia * 0.008) if valor_mercaderia else 0
    costo_base += seguro_carga

    return costo_base

# Función para generar el HTML de la cotización
def generar_html_cotizacion(deposito_info, zona_seleccionada, localidad, peso, distancia, 
                           costo_final, incluir_iva, desea_facturar, cotizacion_id, cantidad, valor_mercaderia=None):
    qr_data = f"""
    ID Cotización: {cotizacion_id}
    Fecha: {datetime.now().strftime("%Y-%m-%d %H:%M")}
    Monto: ${costo_final:,.2f}
    Destino: {localidad} (Zona {zona_seleccionada})
    Depósito: {deposito_info['Nombre']}
    Cantidad: {cantidad}
    Valor Declarado: ${valor_mercaderia:,.2f}""" if valor_mercaderia else ""
    
    qr_base64 = generar_qr(qr_data)
    
    html = f"""
    <html>
    <head>
        <style>
            body {{
                font-family: Arial, sans-serif;
                margin: 20px;
            }}
            .container {{
                max-width: 800px;
                margin: auto;
                padding: 20px;
                border: 1px solid #ccc;
                border-radius: 10px;
                background-color: #f9f9f9;
            }}
            .header {{
                text-align: center;
                margin-bottom: 20px;
            }}
            .header h1 {{
                color: #333;
            }}
            .details {{
                margin-bottom: 20px;
            }}
            .details p {{
                margin: 5px 0;
            }}
            .qr-code {{
                text-align: center;
                margin-top: 20px;
            }}
            .qr-code img {{
                width: 150px;
                height: 150px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Cotizacion Automatizada</h1>
                <h2>Transporte Rio Lavayen</h2>
            </div>
            <div class="details">
                <p><strong>Fecha:</strong> {datetime.now().strftime("%Y-%m-%d %H:%M")}</p>
                <p><strong>Deposito de Origen:</strong> {deposito_info['Nombre']}</p>
                <p><strong>Destino:</strong> {localidad} (Zona {zona_seleccionada})</p>
                <p><strong>Distancia Aproximada:</strong> {distancia} km</p>
                <p><strong>Tipo de Carga:</strong> {peso}</p>
                <p><strong>Cantidad:</strong> {cantidad}</p>
                <p><strong>Valor Declarado:</strong> ${valor_mercaderia:,.2f}</p>
                <p><strong>Incluir IVA:</strong> {"Si" if incluir_iva else "No"}</p>
                <p><strong>Solicitar Seguro de Carga:</strong> {"Si" if desea_facturar else "No"}</p>
                <p><strong>Cotizacion Estimada:</strong> ${costo_final:,.2f}</p>
            </div>
            <div class="qr-code">
                <img src="data:image/png;base64,{qr_base64}" alt="QR Code">
                <p><strong>ID Cotizacion:</strong> {cotizacion_id}</p>
            </div>
        </div>
    </body>
    </html>
    """
    return html

# Función para convertir HTML a PDF
def convertir_html_a_pdf(html, output_path):
    try:
        config = pdfkit.configuration()  # Sin argumentos, pdfkit buscará wkhtmltopdf en las rutas estándar
        pdfkit.from_string(html, output_path, configuration=config)
        return True
    except Exception as e:
        st.error(f"Error al convertir HTML a PDF: {str(e)}")
        return False

# Función para guardar en Supabase
def guardar_cotizacion_supabase(cotizacion_id, datos_cotizacion, html_cotizacion):
    try:
        # Insertar en tabla 'cotizaciones'
        response = supabase.table('cotizaciones').insert(datos_cotizacion).execute()
        
        if hasattr(response, 'error') and response.error:
            st.error(f"Error en cotizaciones: {response.error}")
            return False

        # Insertar en tabla 'cotizaciones_html'
        html_data = {
            "id": cotizacion_id,
            "html_cotizacion": html_cotizacion
        }
        response_html = supabase.table('cotizaciones_html').insert(html_data).execute()
        
        if hasattr(response_html, 'error') and response_html.error:
            st.error(f"Error en cotizaciones_html: {response_html.error}")
            return False
            
        return True
        
    except Exception as e:
        st.error(f"Error general al guardar: {str(e)}")
        return False


# Función para subir el PDF a Supabase Storage (Actualizada)
def subir_pdf_a_supabase(file_path, bucket_name="cotizaciones"):
    try:
        with open(file_path, "rb") as f:
            file_data = f.read()
        
        file_name = os.path.basename(file_path)
        response = supabase.storage.from_(bucket_name).upload(file_name, file_data)
        
        # Construir URL pública manualmente
        public_url = f"{url}/storage/v1/object/public/{bucket_name}/{file_name}"
        return public_url
        
    except Exception as e:
        error_message = str(e)
        if "resource already exists" in error_message:
            # Si el archivo ya existe, devolver URL directamente
            return f"{url}/storage/v1/object/public/{bucket_name}/{file_name}"
        st.error(f"Error al subir el PDF: {error_message}")
        return None
    



# Configuración inicial de la página
st.set_page_config(page_title="Sistema de Cotización Automatizada Transporte Rio Lavayen", layout="wide")
st.title("🚚 Sistema de Cotización Automatizada Transporte Rio Lavayen")

# Inicializar variables de sesión
if 'deposito_seleccionado' not in st.session_state:
    st.session_state.deposito_seleccionado = None
if 'zona_seleccionada' not in st.session_state:
    st.session_state.zona_seleccionada = None
if 'localidad_seleccionada' not in st.session_state:
    st.session_state.localidad_seleccionada = None
if 'valor_mercaderia' not in st.session_state:
    st.session_state.valor_mercaderia = 0  # Inicializar con 0

# --- Contenedor principal ---
main_container = st.container()

with main_container:
    st.header("Configuración Inicial")
    
    # Selección de depósito
    deposito_seleccionado = st.selectbox(
        "Seleccione el depósito:",
        options=[deposito["Nombre"] for deposito in lista_depositos],
        index=None,
        placeholder="Elija un depósito...",
        key='deposito_seleccionado'
    )

    if st.session_state.deposito_seleccionado:
        deposito_info = next(
            (dep for dep in lista_depositos if dep["Nombre"] == st.session_state.deposito_seleccionado),
            None
        )
        origen_lat = deposito_info["Latitud"]
        origen_lon = deposito_info["Longitud"]

        # Selección de zona
        zonas_unicas = list(set(item['ID_Zona'] for item in zonas_localidades))
        zona_seleccionada = st.selectbox(
            "Seleccione la zona de destino:",
            options=sorted(zonas_unicas),
            index=None,
            placeholder="Elija una zona...",
            key='zona_seleccionada'
        )

        if st.session_state.zona_seleccionada:
            localidades_filtradas = [item for item in zonas_localidades if item['ID_Zona'] == st.session_state.zona_seleccionada]
            
            localidad = st.selectbox(
                "Seleccione la localidad de destino:",
                options=[item['Localidad'] for item in localidades_filtradas],
                index=None,
                placeholder="Elija una localidad...",
                key='localidad_seleccionada'
            )

            if st.session_state.localidad_seleccionada:
                destino_info = next(
                    (item for item in localidades_filtradas if item['Localidad'].strip() == st.session_state.localidad_seleccionada.strip()),
                    None
                )
                
                if destino_info:
                    destino_lat = destino_info["Latitud"]
                    destino_lon = destino_info["Longitud"]
                    
                    distancia = calcular_distancia(origen_lat, origen_lon, destino_lat, destino_lon)
                    st.write(f"**Distancia aproximada calculada:** {distancia} km" if distancia else "**Error calculando distancia**")

                    tarifas_filtradas = [item for item in tarifas_base if item['ID_Zona'] == st.session_state.zona_seleccionada]
                    peso = st.selectbox(
                        "Tipo de carga:",
                        options=[item['Descripcion'] for item in tarifas_filtradas],
                        index=None,
                        placeholder="Seleccione tipo de carga...",
                        key='peso_seleccionado'
                    )

                    if st.session_state.peso_seleccionado:
                        # Definir rangos por tipo de carga (sin modificar)
                        carga_rangos = {
                            "BULTO MINIMO (MAXIMO 20 KG)": {"min": 1, "max": 20},
                            "DE 21 KG A 100 KG": {"min": 21, "max": 100},
                            "DE 101 KG A 300 KG": {"min": 101, "max": 300},
                            "DE 301 KG A 500 KG": {"min": 301, "max": 500},
                            "DE 501 KG A 1000 KG": {"min": 501, "max": 1000},
                            "DE 1001 KG A 1500 KG": {"min": 1001, "max": 1500},
                            "DE 1501 KG A 2000 KG": {"min": 1501, "max": 2000},
                            "DE 2001 KG A 2500 KG": {"min": 2001, "max": 2500},
                            "DE 2501 KG A 3000 KG": {"min": 2501, "max": 3000},
                            "DE 3001 KG EN ADELANTE": {"min": 3001, "max": None},
                            "METROS CUBICOS": {"min": 1, "max": 20},
                            "METROS CUBICOS MUDANZA": {"min": 1, "max": 20},
                        }

                        # Normalizar para comparación
                        selected_peso = st.session_state.peso_seleccionado.strip().upper()
                        carga_rangos_normalizado = {
                            key.strip().upper(): value 
                            for key, value in carga_rangos.items()
                        }
                        
                        rango = carga_rangos_normalizado.get(
                            selected_peso, 
                            {"min": 1, "max": None}
                        )

                        cantidad = st.number_input(
                            "Cantidad:",
                            min_value=rango["min"],
                            max_value=rango["max"] if rango["max"] is not None else None,
                            value=rango["min"],
                            key='cantidad'
                        )

                        
                        incluir_iva = st.checkbox("Incluir IVA 21%", value=False, key='incluir_iva')
                        desea_facturar = st.checkbox("Solicitar Seguro de Carga", value=False, key='desea_facturar')
                        if st.session_state.desea_facturar:
                            valor_mercaderia = st.number_input("Valor Declarado:", min_value=0, value=0, key='valor_mercaderia')

                        if all([st.session_state.localidad_seleccionada, distancia, st.session_state.peso_seleccionado]):
                            costo_final = calcular_costo_final(
                                st.session_state.peso_seleccionado,
                                distancia,
                                st.session_state.localidad_seleccionada,
                                st.session_state.incluir_iva,
                                st.session_state.desea_facturar,
                                st.session_state.cantidad,
                                st.session_state.valor_mercaderia
                            )
                            st.session_state.costo_final = costo_final
                            st.subheader(f"**Cotizacion Estimada:** ${costo_final:,.2f}" if costo_final else "**Complete todos los campos**")


                            # Dentro del bloque donde se genera la cotización:
                            # ... (código anterior)

                            # Dentro del bloque donde se genera la cotización:
                            if st.button("📄 Generar Cotización", type="primary", use_container_width=True):
                                if costo_final:
                                    cotizacion_id = str(uuid.uuid4())
                                    
                                    # Mostrar spinner mientras se genera la cotización
                                    with st.spinner("Su cotizacion se esta generando ..."):
                                        html_cotizacion = generar_html_cotizacion(
                                            deposito_info, 
                                            st.session_state.zona_seleccionada,
                                            st.session_state.localidad_seleccionada,
                                            st.session_state.peso_seleccionado,
                                            distancia,
                                            costo_final,
                                            st.session_state.incluir_iva,
                                            st.session_state.desea_facturar,
                                            cotizacion_id,
                                            st.session_state.cantidad,
                                            st.session_state.valor_mercaderia
                                        )

                                        # Obtener datos para Supabase
                                        nombre_zona = next(
                                            (item['Nombre_Zona'] for item in zonas_localidades 
                                            if str(item['ID_Zona']) == str(st.session_state.zona_seleccionada)),
                                            "Zona desconocida"
                                        )
                                        
                                        selected_tarifa = next(
                                            (item for item in tarifas_base 
                                            if item['Descripcion'] == st.session_state.peso_seleccionado 
                                                and str(item['ID_Zona']) == str(st.session_state.zona_seleccionada)),
                                            None
                                        )
                                        
                                        if not selected_tarifa:
                                            st.error("Error en configuración de tarifas")
                                            st.stop()
                                            
                                        try:
                                            peso_value = float(selected_tarifa['Codigo'])
                                        except:
                                            st.error("Formato inválido en código de tarifa")
                                            st.stop()

                                        datos_cotizacion = {
                                            "id": cotizacion_id,
                                            "deposito": deposito_info['Nombre'],
                                            "zona": nombre_zona,
                                            "localidad": st.session_state.localidad_seleccionada,
                                            "peso": peso_value,
                                            "distancia": float(distancia),
                                            "costo_final": float(costo_final),
                                            "seguro_carga": float(st.session_state.valor_mercaderia * 0.008) if st.session_state.valor_mercaderia else 0.0,
                                            "incluir_iva": bool(st.session_state.incluir_iva),
                                            "desea_facturar": bool(st.session_state.desea_facturar),
                                            "cantidad": int(st.session_state.cantidad),
                                            "valor_mercaderia": float(st.session_state.valor_mercaderia)
                                        }

                                        if guardar_cotizacion_supabase(cotizacion_id, datos_cotizacion, html_cotizacion):
                                            # Convertir HTML a PDF
                                            pdf_path = f"{cotizacion_id}.pdf"
                                            with st.spinner("Preparando su cotizacion..."):
                                                if convertir_html_a_pdf(html_cotizacion, pdf_path):
                                                    # Subir el PDF a Supabase
                                                    with st.spinner("Espere unos segundos ..."):
                                                        public_url = subir_pdf_a_supabase(pdf_path)

                                                        st.success("✅ Cotización generada exitosamente valida por 24 hs y el precio reflejado es acorde a la entrega del proveedor a nuestros depositos")

                                                        
                                                        if public_url:
                                                            # Leer PDF para descarga local                                     
                                                            with open(pdf_path, "rb") as pdf_file:
                                                                pdf_bytes = pdf_file.read()

                                                            # Mostrar botones de descarga y WhatsApp
                                                            col1, col2, col3 = st.columns(3)
                                                            with col1:
                                                                st.download_button(
                                                                    label="⬇️ Descargar Cotización (PDF)",
                                                                    data=pdf_bytes,
                                                                    file_name=pdf_path,
                                                                    mime="application/pdf",
                                                                    use_container_width=True
                                                                )
                                                            with col2:
                                                                whatsapp_number = deposito_info['WhatsApp_Administracion_Casa_Central']
                                                                mensaje_whatsapp = textwrap.dedent(f"""
                                                                    *Hola Transporte Rio Lavayen* 👋 Realice una cotizacion online con los siguientes datos:

                                                                    🆔- ID Cotización: *{cotizacion_id}* 
                                                                    📅- Fecha: *{datetime.now().strftime("%Y-%m-%d %H:%M")}*
                                                                    🏢- Depósito de Origen: *{deposito_info['Nombre']}*
                                                                    📍- Destino: *{st.session_state.localidad_seleccionada} (Zona {st.session_state.zona_seleccionada})*
                                                                    🔎- Distancia Aproximada: *{distancia} km*
                                                                    📦- Tipo de Carga: *{st.session_state.peso_seleccionado}*
                                                                    🔢- Cantidad: *{st.session_state.cantidad}*
                                                                    💰- Valor Declarado: *${st.session_state.valor_mercaderia:,.2f}*
                                                                    🛡️- Seguro de Carga: *{"Sí" if st.session_state.desea_facturar else "No"}*
                                                                    🧾- Solicitar Factura: *{"Sí" if st.session_state.incluir_iva else "No"}*
                                                                    💲- Costo Final: *${costo_final:,.2f}*

                                                                    Espero su pronta respuesta. ¡Muchas Gracias! 👌
                                                                """)
                                                                whatsapp_url = f"https://wa.me/{whatsapp_number}?text={urllib.parse.quote(mensaje_whatsapp)}"
                                                                st.markdown(f'<a href="{whatsapp_url}" target="_blank"><button style="background-color: #157F1F; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; width: 100%;">📤 Enviar por WhatsApp</button></a>', unsafe_allow_html=True)
                                                            with col3:
                                                                if st.button("🔄 Nueva Cotización", use_container_width=True):
                                                                    resetear_formulario()
                                                                    st.rerun()

                                                            with st.expander("📋 Vista Previa", expanded=True):
                                                                st.components.v1.html(html_cotizacion, height=800, scrolling=True)

                                                            os.remove(pdf_path)

                            # ... (código posterior)
                else:
                    st.error("Localidad no encontrada")

# Notas al pie
st.divider()
st.caption("© 2024 Transporte Rio Lavayen - Sistema de Cotización Automatizado")