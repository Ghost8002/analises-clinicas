import streamlit as st
import os
import xml.etree.ElementTree as ET
import pandas as pd
import zipfile
import tempfile
import shutil
import re
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph
from io import BytesIO

def limpar_texto_servico(texto):
    # Remove valores monetários (R$ X,XX)
    texto = re.sub(r'R\$\s*\d+[.,]\d+', '', texto)
    # Remove "VALOR UNIT.:", "QTDE.:", "VALOR TOTAL:", "TOTAL GERAL:"
    texto = re.sub(r'(VALOR UNIT\.:|QTDE\.:|VALOR TOTAL:|TOTAL GERAL:)', '', texto)
    # Remove números e espaços extras
    texto = re.sub(r'\s*\d+\s*', '', texto)
    
    # Corrige caracteres especiais
    texto = texto.replace('??', '')
    
    # Adiciona quebra de linha antes de cada "EXAME" ou "CONSULTA"
    texto = re.sub(r'(EXAME|CONSULTA)', r'\n\1', texto)
    
    # Remove espaços múltiplos e trim
    texto = '\n'.join(line.strip() for line in texto.split('\n') if line.strip())
    
    return texto

def criar_pdf(servicos):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []
    
    # Adiciona título
    title = Paragraph("Lista de Serviços", styles['Title'])
    story.append(title)
    story.append(Paragraph("<br/><br/>", styles['Normal']))
    
    # Adiciona cada serviço
    for servico in servicos:
        p = Paragraph(servico, styles['Normal'])
        story.append(p)
        story.append(Paragraph("<br/>", styles['Normal']))
    
    doc.build(story)
    buffer.seek(0)
    return buffer

def analisar_servicos_xml(arquivos_xml):
    resultados = []
    todos_servicos = set()  # Usando set para evitar duplicatas
    
    for arquivo in arquivos_xml:
        try:
            tree = ET.parse(arquivo)
            root = tree.getroot()
            disc = root.find('.//Discriminacao')
            if disc is not None and disc.text:
                servicos = limpar_texto_servico(disc.text.strip()).split('\n')
                todos_servicos.update(servicos)  # Adiciona serviços ao set
                tipo = '\n'.join(servicos)
            else:
                tipo = 'Não encontrado'
        except Exception:
            tipo = 'Erro de leitura'
        resultados.append({'arquivo': os.path.basename(arquivo.name), 'tipo_servico': tipo})
    
    return pd.DataFrame(resultados), sorted(list(todos_servicos))

def extrair_zip(zip_file):
    temp_dir = tempfile.mkdtemp()
    with zipfile.ZipFile(zip_file, 'r') as zip_ref:
        zip_ref.extractall(temp_dir)
    return temp_dir

def processar_arquivos(arquivos):
    arquivos_xml = []
    temp_dirs = []
    
    for arquivo in arquivos:
        if arquivo.name.lower().endswith('.zip'):
            temp_dir = extrair_zip(arquivo)
            temp_dirs.append(temp_dir)
            arquivos_xml.extend([open(os.path.join(temp_dir, f), 'rb') for f in os.listdir(temp_dir) if f.lower().endswith('.xml')])
        elif arquivo.name.lower().endswith('.xml'):
            arquivos_xml.append(arquivo)
    
    return arquivos_xml, temp_dirs

st.set_page_config(page_title="Análise de Serviços XML", layout="wide")
st.title("Análise de Serviços em XML")

arquivos_upload = st.file_uploader("Selecione os arquivos XML ou ZIP", type=['xml', 'zip'], accept_multiple_files=True)

if arquivos_upload and st.button("Analisar"):
    arquivos_xml, temp_dirs = processar_arquivos(arquivos_upload)
    
    if arquivos_xml:
        df, todos_servicos = analisar_servicos_xml(arquivos_xml)
        st.dataframe(df)
        
        # Botão para download dos resultados em CSV
        csv = df.to_csv(index=False)
        st.download_button(
            label="Baixar resultados em CSV",
            data=csv,
            file_name="resultados_analise.csv",
            mime="text/csv"
        )
        
        # Botão para download dos resultados em PDF
        pdf_buffer = criar_pdf(todos_servicos)
        st.download_button(
            label="Baixar lista de serviços em PDF",
            data=pdf_buffer,
            file_name="lista_servicos.pdf",
            mime="application/pdf"
        )
        
        # Limpar arquivos temporários
        for arquivo in arquivos_xml:
            if hasattr(arquivo, 'close'):
                arquivo.close()
        for temp_dir in temp_dirs:
            shutil.rmtree(temp_dir)
    else:
        st.warning("Nenhum arquivo XML encontrado para análise.") 