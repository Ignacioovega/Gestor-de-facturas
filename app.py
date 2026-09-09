import io
import os
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from auth import require_login, render_account_controls
from db import (
    init_db, insert_factura, get_all, update_factura, delete_factura,
    find_duplicate, CATEGORIAS, ESTADOS,
)
from extractor import extract_text_from_pdf, extract_fields, tesseract_available

PDFS_DIR = Path(__file__).parent / "data" / "pdfs"
PDFS_DIR.mkdir(parents=True, exist_ok=True)

st.set_page_config(page_title="Gestor de Facturas", page_icon="🧾", layout="wide")
init_db()
require_login()
render_account_controls()

puede_editar = st.session_state.get("role") in ("admin", "editor")

st.title("🧾 Gestor de Facturas")
st.caption("Subí una factura en PDF y se cargan los datos automáticamente.")

using_claude = bool(os.environ.get("ANTHROPIC_API_KEY"))
if using_claude:
    st.success("Extracción con IA (Claude) activada.", icon="✨")
else:
    st.info(
        "Extracción con reglas básicas (sin IA). Para mejor precisión con cualquier "
        "formato de factura, configurá la variable de entorno ANTHROPIC_API_KEY.",
        icon="ℹ️",
    )

if not tesseract_available():
    st.info(
        "Los PDFs escaneados (que son una imagen, sin texto seleccionable) todavía no se "
        "pueden leer automáticamente. Para activarlo instalá Tesseract OCR (gratis): "
        "https://github.com/UB-Mannheim/tesseract/wiki",
        icon="🖨️",
    )

if puede_editar:
    if "uploader_key" not in st.session_state:
        st.session_state["uploader_key"] = 0

    uploaded_files = st.file_uploader(
        "Subí una o varias facturas en PDF",
        type=["pdf"],
        accept_multiple_files=True,
        key=f"uploader_{st.session_state['uploader_key']}",
    )

    if uploaded_files:
        duplicados_detectados = []
        cuits_invalidos = []
        sin_texto = []

        with st.spinner("Extrayendo datos..."):
            for uploaded in uploaded_files:
                dest = PDFS_DIR / uploaded.name
                dest.write_bytes(uploaded.getvalue())

                text, uso_ocr = extract_text_from_pdf(dest)
                if len(text.strip()) < 5:
                    sin_texto.append(uploaded.name)

                fields = extract_fields(text)
                fields["archivo"] = uploaded.name
                if uso_ocr:
                    fields["metodo_extraccion"] = f"ocr+{fields.get('metodo_extraccion', 'heuristico')}"

                existente = find_duplicate(fields.get("cuit"), fields.get("numero_factura"))
                fields["duplicado"] = "Si" if existente else "No"
                if existente:
                    duplicados_detectados.append((uploaded.name, existente["id"]))
                if fields.get("cuit_valido") == "No":
                    cuits_invalidos.append(uploaded.name)

                insert_factura(fields)

        st.session_state["upload_result"] = {
            "count": len(uploaded_files),
            "duplicados": duplicados_detectados,
            "invalidos": cuits_invalidos,
            "sin_texto": sin_texto,
        }
        st.session_state["uploader_key"] += 1
        st.rerun()

    resultado = st.session_state.pop("upload_result", None)
    if resultado:
        st.success(f"Se procesaron {resultado['count']} factura(s).")
        if resultado["duplicados"]:
            detalle = ", ".join(f"{nombre} (ya existe como factura #{fid})" for nombre, fid in resultado["duplicados"])
            st.warning(f"⚠️ Posibles facturas duplicadas: {detalle}. Revisalas antes de contarlas dos veces.")
        if resultado["invalidos"]:
            st.warning(f"⚠️ CUIT con dígito verificador inválido en: {', '.join(resultado['invalidos'])}. Puede ser un error de lectura del PDF — revisalo a mano.")
        if resultado["sin_texto"]:
            if tesseract_available():
                st.warning(f"⚠️ No se pudo leer texto en: {', '.join(resultado['sin_texto'])}. Puede ser un escaneo de baja calidad — cargá los datos a mano.")
            else:
                st.warning(f"⚠️ No se pudo leer texto en: {', '.join(resultado['sin_texto'])} (parecen ser PDFs escaneados). Instalá Tesseract OCR (gratis) para poder leerlos, o cargá los datos a mano.")
else:
    st.caption("Tu usuario es de solo lectura: podés ver y exportar, pero no subir ni editar facturas.")

st.divider()

rows = get_all()

if not rows:
    st.write("Todavía no subiste ninguna factura.")
else:
    df = pd.DataFrame([dict(r) for r in rows])
    df["vencimiento"] = pd.to_datetime(df["vencimiento"], errors="coerce")

    hoy = pd.Timestamp(date.today())
    pendientes = df[df["estado"].fillna("Pendiente") == "Pendiente"]
    vencidas = pendientes[pendientes["vencimiento"].notna() & (pendientes["vencimiento"] < hoy)]
    por_vencer = pendientes[
        pendientes["vencimiento"].notna()
        & (pendientes["vencimiento"] >= hoy)
        & (pendientes["vencimiento"] <= hoy + pd.Timedelta(days=7))
    ]
    if not vencidas.empty:
        st.error(f"🔴 {len(vencidas)} factura(s) pendiente(s) ya vencieron: " + ", ".join(vencidas["proveedor"].fillna(vencidas["archivo"])))
    if not por_vencer.empty:
        st.warning(f"🟡 {len(por_vencer)} factura(s) pendiente(s) vencen en los próximos 7 días: " + ", ".join(por_vencer["proveedor"].fillna(por_vencer["archivo"])))

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        proveedor_filter = st.text_input("Filtrar por proveedor")
    with col2:
        fecha_filter = st.text_input("Filtrar por fecha (ej. 09/2026)")
    with col3:
        categoria_filter = st.selectbox("Filtrar por categoría", ["Todas"] + CATEGORIAS)
    with col4:
        st.metric("Facturas cargadas", len(df))

    filtered = df.copy()
    if proveedor_filter:
        filtered = filtered[filtered["proveedor"].fillna("").str.contains(proveedor_filter, case=False)]
    if fecha_filter:
        filtered = filtered[filtered["fecha"].fillna("").str.contains(fecha_filter, case=False)]
    if categoria_filter != "Todas":
        filtered = filtered[filtered["categoria"].fillna("") == categoria_filter]

    st.subheader("Facturas")
    edited = st.data_editor(
        filtered,
        column_config={
            "id": st.column_config.NumberColumn("ID", disabled=True),
            "archivo": st.column_config.TextColumn("Archivo", disabled=True),
            "categoria": st.column_config.SelectboxColumn("Categoría", options=CATEGORIAS),
            "estado": st.column_config.SelectboxColumn("Estado", options=ESTADOS),
            "vencimiento": st.column_config.DateColumn("Vencimiento", format="DD/MM/YYYY"),
            "cuit_valido": st.column_config.TextColumn("CUIT válido", disabled=True),
            "duplicado": st.column_config.TextColumn("¿Duplicado?", disabled=True),
            "metodo_extraccion": st.column_config.TextColumn("Método", disabled=True),
            "subido_en": st.column_config.TextColumn("Subido", disabled=True),
        },
        hide_index=True,
        use_container_width=True,
        disabled=not puede_editar,
        key="editor",
    )

    col_save, col_export = st.columns([1, 1])
    with col_save:
        if puede_editar and st.button("Guardar cambios en la tabla"):
            editable_cols = [
                "proveedor", "cuit", "numero_factura", "fecha", "total", "moneda",
                "categoria", "estado", "vencimiento",
            ]
            for _, row in edited.iterrows():
                valores = {}
                for c in editable_cols:
                    valor = row[c]
                    if c == "vencimiento":
                        valor = valor.strftime("%Y-%m-%d") if pd.notna(valor) else None
                    valores[c] = valor
                update_factura(int(row["id"]), valores)
            st.success("Cambios guardados.")
            st.rerun()

    with col_export:
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
            filtered.drop(columns=["archivo"], errors="ignore").to_excel(writer, index=False, sheet_name="Facturas")
        st.download_button(
            "Descargar Excel",
            data=excel_buffer.getvalue(),
            file_name="facturas.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    if puede_editar:
        with st.expander("Eliminar una factura"):
            options = {f"#{r['id']} - {r['archivo']}": r["id"] for r in filtered.to_dict("records")}
            if options:
                selected = st.selectbox("Elegí una factura", list(options.keys()))
                if st.button("Eliminar", type="primary"):
                    delete_factura(options[selected])
                    st.rerun()

    try:
        totales_num = pd.to_numeric(
            filtered["total"].astype(str).str.replace(".", "", regex=False).str.replace(",", ".", regex=False),
            errors="coerce",
        )
        st.metric("Suma de totales (filtrado)", f"${totales_num.sum():,.2f}")

        if filtered["categoria"].notna().any():
            st.caption("Totales por categoría")
            cat_totales = (
                pd.DataFrame({"categoria": filtered["categoria"].fillna("Sin categoría"), "total": totales_num})
                .groupby("categoria")["total"]
                .sum()
                .sort_values(ascending=False)
            )
            st.bar_chart(cat_totales)
    except Exception:
        pass
