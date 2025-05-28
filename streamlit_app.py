import streamlit as st
import os
import xml.etree.ElementTree as ET
import pandas as pd
import zipfile
import tempfile
import shutil
import re
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph
from io import BytesIO
from PyPDF2 import PdfReader

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
            
            # Registra os namespaces encontrados
            namespaces = {'ns': root.tag.split('}')[0].strip('{')} if '}' in root.tag else {}
            
            # Tenta encontrar a tag Discriminacao em diferentes caminhos possíveis
            disc = None
            # Tenta sem namespace
            disc = root.find('.//Discriminacao')
            if disc is None:
                # Tenta com namespace
                for ns in namespaces.values():
                    disc = root.find(f'.//{{{ns}}}Discriminacao')
                    if disc is not None:
                        break
            
            if disc is None:
                # Tenta caminhos mais específicos
                paths = [
                    './/Servico/Discriminacao',
                    './/InfDeclaracaoPrestacaoServico/Servico/Discriminacao',
                    './/DeclaracaoPrestacaoServico//Discriminacao'
                ]
                for path in paths:
                    disc = root.find(path)
                    if disc is not None:
                        break
                    
                    # Tenta com namespace
                    for ns in namespaces.values():
                        disc = root.find(f'.//{{{ns}}}Servico/{{{ns}}}Discriminacao')
                        if disc is not None:
                            break
            
            if disc is not None and disc.text:
                servicos = limpar_texto_servico(disc.text.strip()).split('\n')
                todos_servicos.update(servicos)  # Adiciona serviços ao set
                tipo = '\n'.join(servicos)
            else:
                tipo = 'Não encontrado'
        except Exception as e:
            tipo = f'Erro de leitura: {str(e)}'
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

# Mapeamento de correções comuns de ortografia
TYPO_MAP = {
    r"\bODOTOLOG":         "ODONTOLÓGICO",
    r"\bODONDOLOG":        "ODONTOLÓGICO",
    r"\bONDOTOLOG":        "ODONTOLÓGICO",
    r"\bOSONTOLOG":        "ODONTOLÓGICO",
    r"\bODODONTOLOG":      "ODONTOLÓGICO",
    r"\bSEEVIÇO":          "SERVIÇO",
    r"\bSEVIÇO":           "SERVIÇO",
    r"\bSERVIÇO ODONTOLOGICO":      "SERVIÇO ODONTOLÓGICO",
    r"\bSERVIÇOS ODONTOLÓGICAS":    "SERVIÇOS ODONTOLÓGICOS",
    r"\bAPLICAÇÃO TOPICA":          "APLICAÇÃO TÓPICA",
    r"\bULTRASSO\b":                "ULTRASSOM",
    r"\bCLNICA\b":  "CLINICA"
}

def clean_services(text: str) -> list:
    """
    Extrai linhas de texto, aplica correções de ortografia e remove duplicatas.
    Retorna lista ordenada de serviços limpos.
    """
    lines = re.split(r'\r\n|\r|\n', text)
    seen, cleaned = set(), []
    for line in lines:
        s = line.strip().upper()
        if not s:
            continue
        # aplica cada correção de typo
        for pattern, replace in TYPO_MAP.items():
            s = re.sub(pattern, replace, s)
        # remove múltiplos espaços e pontuações redundantes
        s = re.sub(r'\s+', ' ', s).strip(' .,-')
        if s and s not in seen:
            seen.add(s)
            cleaned.append(s)
    return sorted(cleaned)

def process_pdfs(input_files, output_pdf):
    # inicializa o PDF de saída
    c = canvas.Canvas(output_pdf, pagesize=A4)
    width, height = A4

    # percorre todos os PDFs
    for uploaded_file in input_files:
        # Salva o arquivo temporariamente
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_path = tmp_file.name

        try:
            reader = PdfReader(tmp_path)
            
            # extrai texto de todas as páginas
            full_text = ""
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    full_text += t + "\n"

            # processa serviços
            services = clean_services(full_text)
            company = os.path.splitext(uploaded_file.name)[0]

            # escreve no PDF
            c.setFont("Helvetica-Bold", 14)
            c.drawString(40, height - 50, f"Empresa: {company}")
            c.setFont("Helvetica", 11)
            y = height - 80
            for svc in services:
                if y < 50:
                    c.showPage()
                    c.setFont("Helvetica", 11)
                    y = height - 50
                c.drawString(50, y, f"- {svc}")
                y -= 15
            c.showPage()

        finally:
            # Limpa o arquivo temporário
            os.unlink(tmp_path)

    c.save()
    return output_pdf

# Configuração da página Streamlit
st.set_page_config(page_title="Análise de Serviços", layout="wide")

# Criação de abas para diferentes funcionalidades
tab1, tab2 = st.tabs(["Análise XML", "Correção PDF"])

with tab1:
    st.title("Análise de Serviços em XML")
    arquivos_upload = st.file_uploader("Selecione os arquivos XML ou ZIP", type=['xml', 'zip'], accept_multiple_files=True)

    if arquivos_upload and st.button("Analisar XML"):
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

with tab2:
    st.title("Correção de PDFs Odontológicos")
    uploaded_files = st.file_uploader(
        "Selecione os PDFs para processar",
        type=['pdf'],
        accept_multiple_files=True
    )

    if uploaded_files:
        if st.button("Processar PDFs"):
            with st.spinner("Processando PDFs..."):
                # Cria um diretório temporário para o PDF de saída
                with tempfile.TemporaryDirectory() as temp_dir:
                    output_pdf = os.path.join(temp_dir, "Servicos_Clinicas_Corrigidos.pdf")
                    
                    # Processa os PDFs
                    process_pdfs(uploaded_files, output_pdf)
                    
                    # Lê o PDF gerado
                    with open(output_pdf, 'rb') as f:
                        pdf_bytes = f.read()
                    
                    # Botão para download
                    st.download_button(
                        label="Baixar PDF Corrigido",
                        data=pdf_bytes,
                        file_name="Servicos_Clinicas_Corrigidos.pdf",
                        mime="application/pdf"
                    )
                    
                    st.success("PDFs processados com sucesso!") 
