import csv
import smtplib
import urllib.request
import json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ==========================================
# CONFIGURACIÓN DE CORREO
# ==========================================
REMITENTE = "christianherbert1039@gmail.com"
CONTRASENA = "pbuymthsprotiiqz"
DESTINATARIO = "christianherbert1039@gmail.com"

def buscar_en_boe():
    """Consulta los últimos datos del BOE buscando licitaciones de mutuas y seguros."""
    resultados_boe = []
    try:
        # URL de la API del BOE para el sumario diario (ejemplo estándar o de referencia)
        url_boe = "https://www.boe.es/datosabiertos/api/boe/sumario"
        req = urllib.request.Request(
            url_boe, 
            headers={'Accept': 'application/json'}
        )
        
        with urllib.request.urlopen(req, timeout=10) as respuesta:
            datos = json.loads(respuesta.read().decode('utf-8'))
            
            # Recorremos la estructura del BOE buscando coincidencias clave
            # (Nota: filtramos por términos como 'mutua', 'seguro' o 'mutuas')
            palabras_clave = ["mutua", "mutuas", "seguro", "seguros"]
            
            # Navegamos por los departamentos/secciones del sumario del BOE si la estructura responde
            diario = datos.get("sumario", {}).get("diario", [])
            for seccion in diario:
                for departamento in seccion.get("departamento", []):
                    for epigrafe in departamento.get("epigrafe", []):
                        for item in epigrafe.get("item", []):
                            titulo = item.get("titulo", "").lower()
                            # Si el título menciona alguna palabra clave de interés
                            if any(palabra in titulo for palabra in palabras_clave):
                                url_item = item.get("urlPdf", {}).get("#text", "https://www.boe.es")
                                resultados_boe.append({
                                    "tipo_hallazgo": "BOE (Mutuas/Seguros)",
                                    "texto": item.get("titulo", "Sin descripción"),
                                    "Link": url_item
                                })
        print("-> Búsqueda en el BOE completada con éxito.")
    except Exception as e:
        print(f"-> AVISO: No se pudo conectar al BOE en este momento ({e}). Continuando con los archivos locales...")
    
    return resultados_boe

def main():
    print("=== PROCESANDO ALERTAS UNIFICADAS Y BOE ===")
    
    resultados_totales = []

    # 1. Leer Subvenciones locales (si existe el archivo)
    try:
        with open("resultados_subvenciones.csv", mode="r", encoding="utf-8") as f:
            lector = csv.DictReader(f)
            for fila in lector:
                fila["tipo_hallazgo"] = "Subvención"
                resultados_totales.append(fila)
        print("-> Subvenciones locales cargadas correctamente.")
    except Exception:
        print("-> No se encontró el archivo de subvenciones locales.")

    # 2. Leer Licitaciones locales (si existe el archivo)
    try:
        with open("resultados_licitaciones.csv", mode="r", encoding="utf-8") as f:
            lector = csv.DictReader(f)
            for fila in lector:
                fila["tipo_hallazgo"] = "Licitación"
                resultados_totales.append(fila)
        print("-> Licitaciones locales cargadas correctamente.")
    except Exception:
        print("-> No se encontró el archivo de licitaciones locales.")

    # 3. Consultar directamente el BOE para Mutuas y Seguros
    resultados_boe = buscar_en_boe()
    resultados_totales.extend(resultados_boe)

    total = len(resultados_totales)

    # 4. Si hay algo nuevo, armar el correo y enviarlo
    if total > 0:
        print(f"\nGenerando informe unificado con {total} novedades encontradas...")

        filas_tabla = ""
        for r in resultados_totales:
            tipo = r.get('tipo_hallazgo', '')
            if "Subvención" in tipo:
                color_tipo = "#2c3e50"
            elif "Licitación" in tipo:
                color_tipo = "#e67e22"
            else:
                color_tipo = "#8e44ad" # Morado para BOE / Mutuas

            filas_tabla += f"""
            <tr style="border-bottom: 1px solid #e0e0e0;">
                <td style="padding: 12px; font-weight: bold; color: {color_tipo};">{tipo}</td>
                <td style="padding: 12px; color: #555;">{r.get('texto', 'Sin descripción')}</td>
                <td style="padding: 12px;"><a href="{r.get('Link', '#')}" style="color: #3498db; text-decoration: none;">Ver enlace</a></td>
            </tr>
            """

        html_contenido = f"""
        <!DOCTYPE html>
        <html>
        <head><meta charset="utf-8"></head>
        <body style="font-family: Arial, sans-serif; background-color: #f4f6f9; margin: 0; padding: 20px;">
            <div style="max-width: 650px; margin: auto; background: #ffffff; padding: 30px; border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.05);">
                <h2 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; margin-top: 0;">
                    📊 Resumen Automatizado: PsiqueIntegral (BOE + Locales)
                </h2>
                <p style="color: #555; font-size: 15px;">Hola Christian,</p>
                <p style="color: #555; font-size: 15px;">Se han consolidado todas las fuentes y hay <b>{total}</b> oportunidades detectadas:</p>
                <table style="width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 13px;">
                    <thead>
                        <tr style="background-color: #f8f9fa; text-align: left; border-bottom: 2px solid #ddd;">
                            <th style="padding: 12px; color: #333;">Categoría</th>
                            <th style="padding: 12px; color: #333;">Descripción</th>
                            <th style="padding: 12px; color: #333;">Acción</th>
                        </tr>
                    </thead>
                    <tbody>
                        {filas_tabla}
                    </tbody>
                </table>
                <p style="color: #888; font-size: 12px; margin-top: 30px; text-align: center; border-top: 1px solid #eee; padding-top: 15px;">
                    PsiqueIntegral — Sistema de Gestión Automatizada
                </p>
            </div>
        </body>
        </html>
        """

        mensaje = MIMEMultipart("alternative")
        mensaje["Subject"] = f"Alerta PsiqueIntegral: {total} Novedades (Incluye BOE Mutuas)"
        mensaje["From"] = REMITENTE
        mensaje["To"] = DESTINATARIO
        mensaje.attach(MIMEText(html_contenido, "html"))

        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as servidor:
                servidor.login(REMITENTE, CONTRASENA)
                servidor.sendmail(REMITENTE, DESTINATARIO, mensaje.as_string())
            print("¡Correo unificado con BOE enviado con éxito a tu bandeja!")
        except Exception as e:
            print(f"Error al enviar el correo: {e}")
    else:
        print("\nNo hay resultados nuevos para enviar.")

if __name__ == "__main__":
    main()