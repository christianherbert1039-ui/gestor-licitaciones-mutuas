import os, csv, re, smtplib, requests, unicodedata, time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ============================================================
# CONFIGURACION
# ============================================================

REMITENTE = "christianherbert1039@gmail.com"
DESTINATARIOS = ["martinherbert1996@gmail.com"]
PASSWORD = "pbuymthsprotiiqz"

CSV_FILE = "resultados_licitaciones.csv"
INFORME_FILE = "informe_psique.txt"

PLACSP_URL = ("https://contrataciondelestado.es/sindicacion/"
              "sindicacion_643/licitacionesPerfilesContratanteCompleto3.atom")

CPV_PSIQUE = {"85121270","85121200","85121000","85120000","85100000",
              "85312300","85312320","85312310","85312500","85141000","85143000"}

CPV_SEGUROS = {"66510000","66511000","66512000","66512100","66512200","66513000"}

KEYWORDS_PSIQUE = ["psiquiatr","psicolog","salud mental","neuropsicolog","pericial",
    "evaluacion psicologica","evaluación psicológica","atencion psicologica",
    "atención psicológica","asistencia psicologica","asistencia psicológica",
    "psicoterapia","terapia psicologica","terapia psicológica",
    "acompañamiento emocional","acompanamiento emocional","apoyo psicologico",
    "apoyo psicológico","rehabilitacion psicosocial","rehabilitación psicosocial",
    "trastorno mental"]

ASEGURADORAS = ["MAPFRE","Mutua Madrileña","Pelayo","Generali","Reale","Zurich",
    "Linea Directa","Línea Directa","MGS","A.M.A.","AMA Seguros","DKV","Sanitas",
    "Helvetia","Caser"]

KEYWORDS_SEGUROS = ["psiquiatr","psicolog","salud mental","neuropsicolog",
    "psicoterapia","asistencia psicologica","asistencia psicológica",
    "apoyo psicologico","apoyo psicológico","acompañamiento emocional",
    "acompanamiento emocional","trauma","accidente","siniestro",
    "asistencia sanitaria","asistencia medica","asistencia médica",
    "prevencion","prevención","empleados","trabajadores"]


# ============================================================
# UTILIDADES
# ============================================================

def normalizar(texto):
    if not texto:
        return ""
    t = unicodedata.normalize("NFD", str(texto))
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return t.lower().strip()


def contiene_keyword(texto, lista):
    tn = normalizar(texto)
    return any(normalizar(p) in tn for p in lista)


def extraer_cpvs(texto):
    if not texto:
        return set()
    encontrados = set()
    for p in re.findall(r"\b\d{2}[.\s]?\d{2}[.\s]?\d{2}[.\s]?\d{2}(?:-\d)?\b", texto):
        limpio = re.sub(r"[^0-9]", "", p)
        if len(limpio) >= 8:
            encontrados.add(limpio[:8])
    return encontrados


def parsear_fecha(texto):
    """
    Devuelve (fecha_datetime, tenia_hora_real).
    Si la fuente solo da el día, se asume 23:59 y se marca tenia_hora_real=False.
    """
    if not texto:
        return None, False
    texto = texto.strip()
    formatos = [
        ("%Y-%m-%dT%H:%M:%S", True),
        ("%Y-%m-%dT%H:%M", True),
        ("%Y-%m-%d", False),
        ("%d/%m/%Y %H:%M", True),
        ("%d/%m/%Y", False),
        ("%d-%m-%Y %H:%M", True),
        ("%d-%m-%Y", False),
    ]
    for formato, tiene_hora in formatos:
        try:
            f = datetime.strptime(texto, formato)
            if not tiene_hora:
                f = f.replace(hour=23, minute=59)
            return f, tiene_hora
        except Exception:
            pass
    return None, False


def formatear_fecha(fecha, tenia_hora):
    if not fecha:
        return "No indicada"
    if tenia_hora:
        return fecha.strftime("%d/%m/%Y %H:%M")
    return fecha.strftime("%d/%m/%Y") + " (fin del día)"


def calcular_estado(fecha):
    if not fecha:
        return "POR VERIFICAR"
    return "VIGENTE" if fecha >= datetime.now() else "CERRADA"


def extraer_fecha_limite(entry):
    """
    Busca la fecha límite real de presentación en el XML Atom de PLACSP.
    Prioriza TenderSubmissionDeadline y luego endDate/endTime.
    """
    prioridades = [
        "tendersubmissiondeadline",
        "enddate",
        "endtime",
    ]

    candidatos = []

    for elem in entry.iter():
        tag = elem.tag.lower()
        texto = (elem.text or "").strip()
        if not texto:
            continue
        for i, clave in enumerate(prioridades):
            if clave in tag:
                candidatos.append((i, texto))
                break

    candidatos.sort(key=lambda x: x[0])

    for _, texto in candidatos:
        fecha, tenia_hora = parsear_fecha(texto)
        if fecha:
            return fecha, tenia_hora

    return None, False


def extraer_link(entry):
    enlaces = []
    for elem in entry:
        if not elem.tag.lower().endswith("link"):
            continue
        href = elem.attrib.get("href", "")
        rel = elem.attrib.get("rel", "").lower()
        if href:
            enlaces.append((rel, href))
    for rel, href in enlaces:
        if rel == "alternate":
            return href
    for rel, href in enlaces:
        if "detalle_licitacion" in href.lower():
            return href
    for rel, href in enlaces:
        if href.startswith("http") and "sindicacion" not in href.lower():
            return href
    return ""


def extraer_titulo_resumen(entry):
    titulo = ""
    resumen = ""
    for hijo in entry:
        tag = hijo.tag.lower()
        if tag.endswith("title"):
            titulo = hijo.text or ""
        elif tag.endswith("summary"):
            resumen = hijo.text or ""
    return titulo, resumen


# ============================================================
# PLACSP
# ============================================================

def buscar_en_placsp(modo):
    resultados = []
    print()
    print(f"=== PLACSP | {modo.upper()} ===")
    try:
        r = requests.get(PLACSP_URL, timeout=60)
        r.raise_for_status()
        raiz = ET.fromstring(r.content)
    except Exception as e:
        print("-> Error PLACSP:", e)
        return resultados

    for entry in raiz.iter():
        if not entry.tag.lower().endswith("entry"):
            continue
        titulo, resumen = extraer_titulo_resumen(entry)
        texto = titulo + " " + resumen
        cpvs = extraer_cpvs(texto)

        if modo == "psique":
            coincide = bool(cpvs.intersection(CPV_PSIQUE)) or contiene_keyword(texto, KEYWORDS_PSIQUE)
        else:
            coincide_cpv = bool(cpvs.intersection(CPV_SEGUROS))
            coincide_aseg = any(normalizar(a) in normalizar(texto) for a in ASEGURADORAS)
            coincide_salud = contiene_keyword(texto, KEYWORDS_SEGUROS)
            coincide = coincide_cpv or (coincide_aseg and coincide_salud)

        if not coincide:
            continue

        fecha_limite, tenia_hora = extraer_fecha_limite(entry)
        estado = calcular_estado(fecha_limite)
        enlace = extraer_link(entry)
        fuente = "PLACSP" if modo == "psique" else "PLACSP - Seguros/Mutuas"

        resultados.append({
            "fuente": fuente,
            "titulo": titulo.strip(),
            "fecha_limite": formatear_fecha(fecha_limite, tenia_hora),
            "estado": estado,
            "link": enlace,
        })

    print(f"-> Coincidencias PLACSP {modo}: {len(resultados)}")
    return resultados


# ============================================================
# BOE
# ============================================================

def crear_driver():
    op = webdriver.ChromeOptions()
    op.add_argument("--start-maximized")
    op.add_argument("--disable-notifications")
    op.add_argument("--disable-popup-blocking")
    return webdriver.Chrome(options=op)


def _campo_busqueda(driver):
    for c in driver.find_elements(By.CSS_SELECTOR, "input"):
        if (c.get_attribute("type") or "").lower() in ("text", "search"):
            return c
    return None


def _titulo_boe(cuerpo, cpv):
    for linea in [x.strip() for x in cuerpo.splitlines() if x.strip()][:30]:
        if "anuncio" in linea.lower():
            return linea
    return "Anuncio BOE - CPV " + cpv


def _fecha_boe(cuerpo):
    meses = {"enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,
             "julio":7,"agosto":8,"septiembre":9,"octubre":10,"noviembre":11,"diciembre":12}
    for d, m, a in re.findall(r"(\d{1,2}) de ([a-záéíóú]+) de (\d{4})", cuerpo.lower()):
        if m in meses:
            try:
                return datetime(int(a), meses[m], int(d), 23, 59)
            except Exception:
                pass
    return None


def buscar_boe_selenium():
    resultados = []
    print()
    print("=== BOE | CONTRATACION PUBLICA | SELENIUM ===")
    driver = None
    try:
        driver = crear_driver()
        wait = WebDriverWait(driver, 20)
        print("-> Abriendo BOE...")
        driver.get("https://www.boe.es/buscar/")
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        print("-> BOE abierto:", driver.title)

        cpvs = ["85121270","85121200","85121000","85312300","85312500","85141000","85143000"]
        vistas = set()

        for cpv in cpvs:
            print("-> Buscando CPV:", cpv)
            try:
                driver.get("https://www.boe.es/buscar/")
                wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                campo = _campo_busqueda(driver)
                if not campo:
                    print("   -> No se encontró campo de búsqueda.")
                    continue
                campo.clear()
                campo.send_keys(cpv)
                campo.send_keys(Keys.ENTER)
                time.sleep(3)

                candidatos = []
                for e in driver.find_elements(By.TAG_NAME, "a"):
                    try:
                        t = (e.text or "").strip()
                        h = e.get_attribute("href") or ""
                        if h and "boe.es" in h.lower():
                            candidatos.append((t, h))
                    except Exception:
                        continue

                for titulo, href in candidatos:
                    if href in vistas:
                        continue
                    if ("/buscar/doc.php?id=BOE-" not in href
                            and "/diario_boe/txt.php?id=BOE-" not in href):
                        continue
                    vistas.add(href)
                    try:
                        driver.get(href)
                        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                        cuerpo = driver.find_element(By.TAG_NAME, "body").text
                    except Exception:
                        continue
                    cn = normalizar(cuerpo)
                    if "contratacion del sector publico" not in cn:
                        continue
                    if not extraer_cpvs(cuerpo).intersection(CPV_PSIQUE):
                        continue
                    if "anuncio de licitacion" not in cn:
                        continue
                    titulo_final = titulo or _titulo_boe(cuerpo, cpv)
                    fecha_limite = _fecha_boe(cuerpo)
                    estado = calcular_estado(fecha_limite)
                    resultados.append({
                        "fuente": "BOE - Contratación",
                        "titulo": titulo_final,
                        "fecha_limite": formatear_fecha(fecha_limite, bool(fecha_limite)),
                        "estado": estado,
                        "link": href,
                    })
            except Exception as e:
                print("   -> Error buscando", cpv, ":", e)

        unicos = {}
        for r in resultados:
            unicos.setdefault(r["link"], r)
        resultados = list(unicos.values())
        print("-> BOE: coincidencias:", len(resultados))
    except Exception as e:
        print("-> Error general Selenium BOE:", e)
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
    return resultados


# ============================================================
# CSV
# ============================================================

def cargar_csv():
    if not os.path.exists(CSV_FILE):
        return []
    resultados = []
    try:
        with open(CSV_FILE, "r", encoding="utf-8-sig", newline="") as f:
            for fila in csv.DictReader(f):
                resultados.append({
                    "fuente": fila.get("fuente", ""),
                    "titulo": fila.get("titulo", ""),
                    "fecha_limite": fila.get("fecha_limite", ""),
                    "estado": fila.get("estado", "POR VERIFICAR"),
                    "link": fila.get("link", ""),
                })
    except Exception as e:
        print("-> Error leyendo CSV:", e)
    return resultados


def guardar_csv(resultados):
    try:
        with open(CSV_FILE, "w", encoding="utf-8-sig", newline="") as f:
            campos = ["fuente","titulo","fecha_limite","estado","link"]
            w = csv.DictWriter(f, fieldnames=campos)
            w.writeheader()
            for r in resultados:
                w.writerow({k: r.get(k, "") for k in campos})
        print("-> CSV local actualizado:", CSV_FILE)
    except Exception as e:
        print("-> Error guardando CSV:", e)


def deduplicar(resultados):
    unicos = {}
    for r in resultados:
        clave = (r.get("link", "") or "").strip() or normalizar(r.get("titulo", ""))
        if clave and clave not in unicos:
            unicos[clave] = r
    return list(unicos.values())


# ============================================================
# INFORME (texto plano, para archivo .txt)
# ============================================================

def _bloque(titulo, lista):
    lineas = ["", "=" * 70, titulo, "=" * 70, ""]
    if not lista:
        lineas += ["(Sin resultados)", ""]
        return lineas
    for i, r in enumerate(lista, 1):
        lineas += [
            f"{i}. [{r.get('fuente','')}]",
            "   TITULO: " + r.get("titulo", ""),
            "   PLAZO: " + r.get("fecha_limite", "No indicada"),
            "   ESTADO: " + r.get("estado", "POR VERIFICAR"),
            "   ENLACE: " + r.get("link", ""),
            "",
        ]
    return lineas


def generar_informe(resultados):
    ahora = datetime.now().strftime("%d/%m/%Y %H:%M")
    vigentes = [r for r in resultados if r.get("estado") == "VIGENTE"]
    por_ver = [r for r in resultados if r.get("estado") == "POR VERIFICAR"]
    cerradas = [r for r in resultados if r.get("estado") == "CERRADA"]

    lineas = ["PSIQUE - ALERTA INTEGRAL", "=" * 70,
              "Generado: " + ahora, "",
              "VIGENTES: " + str(len(vigentes)),
              "POR VERIFICAR: " + str(len(por_ver)),
              "HISTORICAS (cerradas): " + str(len(cerradas))]
    lineas += _bloque("VIGENTES", vigentes)
    lineas += _bloque("POR VERIFICAR", por_ver)
    lineas += _bloque("HISTORICAS", cerradas)

    informe = "\n".join(lineas)
    try:
        with open(INFORME_FILE, "w", encoding="utf-8") as f:
            f.write(informe)
        print("Informe guardado:", INFORME_FILE)
    except Exception as e:
        print("Error guardando informe:", e)
    return informe


# ============================================================
# EMAIL (HTML con enlaces clicables)
# ============================================================

def _construir_html(resultados):
    ahora = datetime.now().strftime("%d/%m/%Y %H:%M")

    vigentes = [r for r in resultados if r.get("estado") == "VIGENTE"]
    por_ver = [r for r in resultados if r.get("estado") == "POR VERIFICAR"]
    cerradas = [r for r in resultados if r.get("estado") == "CERRADA"]

    def bloque(titulo, lista):
        html = f"<h2 style='color:#003366;border-bottom:2px solid #003366;padding-bottom:5px;'>{titulo}</h2>"
        if not lista:
            html += "<p><i>(Sin resultados)</i></p>"
            return html
        for i, r in enumerate(lista, 1):
            enlace = r.get("link", "") or ""
            if enlace:
                boton = (
                    f"<p style='margin:15px 0;'>"
                    f"<a href='{enlace}' "
                    f"style='display:inline-block;padding:10px 20px;"
                    f"background:#003366;color:#ffffff !important;"
                    f"text-decoration:none;border-radius:5px;"
                    f"font-weight:bold;font-family:Arial;'>"
                    f"👉 Abrir oportunidad</a></p>"
                    f"<p style='font-size:11px;color:#666;word-break:break-all;'>"
                    f"Enlace: <a href='{enlace}' style='color:#0066cc;'>{enlace}</a></p>"
                )
            else:
                boton = "<p><i>(Sin enlace disponible)</i></p>"

            html += (
                f"<div style='margin-bottom:25px;padding:15px;"
                f"border:1px solid #ddd;border-radius:6px;"
                f"background:#fafafa;font-family:Arial,sans-serif;'>"
                f"<p style='margin:0 0 8px 0;font-size:15px;'><b>{i}. {r.get('titulo', '')}</b></p>"
                f"<p style='margin:4px 0;font-size:13px;'><b>Fuente:</b> {r.get('fuente', '')}</p>"
                f"<p style='margin:4px 0;font-size:13px;'><b>Plazo:</b> {r.get('fecha_limite', 'No indicada')}</p>"
                f"<p style='margin:4px 0;font-size:13px;'><b>Estado:</b> {r.get('estado', 'POR VERIFICAR')}</p>"
                f"{boton}"
                f"</div>"
            )
        return html

    cuerpo = f"""<html>
<body style="font-family:Arial,sans-serif;color:#222;max-width:800px;">
<h1 style="color:#003366;">PSIQUE - ALERTA INTEGRAL</h1>
<p><b>Generado:</b> {ahora}</p>
<p style="font-size:14px;">
  <b>Vigentes:</b> {len(vigentes)} &nbsp;|&nbsp;
  <b>Por verificar:</b> {len(por_ver)} &nbsp;|&nbsp;
  <b>Cerradas:</b> {len(cerradas)}
</p>
<hr>
{bloque("VIGENTES", vigentes)}
{bloque("POR VERIFICAR", por_ver)}
{bloque("HISTÓRICAS (cerradas)", cerradas)}
<hr>
<p style="font-size:11px;color:#888;">
  Este correo ha sido generado automáticamente por Psique Integral.
</p>
</body></html>"""
    return cuerpo


def enviar_correo(informe, resultados):
    print()
    print("Enviando correo...")

    if not REMITENTE or not DESTINATARIOS or not PASSWORD:
        print("-> AVISO: faltan credenciales. No se envía correo.")
        return

    try:
        m = MIMEMultipart("alternative")
        m["From"] = REMITENTE
        m["To"] = ", ".join(DESTINATARIOS)
        m["Subject"] = Header("PSIQUE - ALERTA INTEGRAL", "utf-8")

        m.attach(MIMEText(informe, "plain", "utf-8"))
        m.attach(MIMEText(_construir_html(resultados), "html", "utf-8"))

        with smtplib.SMTP_SSL(
            "smtp.gmail.com", 465, local_hostname="localhost"
        ) as s:
            s.login(REMITENTE, PASSWORD)
            s.sendmail(REMITENTE, DESTINATARIOS, m.as_string())

        print("-> Correo enviado correctamente.")

    except Exception as e:
        print("-> ERROR enviando correo:", e)


# ============================================================
# PROGRAMA PRINCIPAL
# ============================================================

def main():
    print()
    print("PSIQUE - ALERTA INTEGRAL")
    print("=" * 70)

    placsp_psique = buscar_en_placsp("psique")
    placsp_seguros = buscar_en_placsp("seguros")
    boe = buscar_boe_selenium()

    antiguos = cargar_csv()
    print("-> CSV local:", len(antiguos), "registros.")

    todos = deduplicar(placsp_psique + placsp_seguros + boe)
    guardar_csv(todos)

    print()
    print("Generando informe con", len(todos), "resultados.")
    informe = generar_informe(todos)
    enviar_correo(informe, todos)

    print()
    print("PROCESO TERMINADO.")


if __name__ == "__main__":
    main()
