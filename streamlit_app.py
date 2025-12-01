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

def buscar_tag_xml(root, tag_name, namespaces=None, paths=None):
    """
    Busca uma tag XML de forma flexível, tentando com e sem namespace.
    
    Args:
        root: Elemento raiz do XML
        tag_name: Nome da tag a buscar
        namespaces: Dicionário de namespaces
        paths: Lista de caminhos específicos para tentar
    
    Returns:
        Elemento encontrado ou None
    """
    if namespaces is None:
        namespaces = {}
    if paths is None:
        paths = []
    
    # Tenta sem namespace primeiro
    elemento = root.find(f'.//{tag_name}')
    if elemento is not None:
        return elemento
    
    # Tenta com namespace
    for ns in namespaces.values():
        elemento = root.find(f'.//{{{ns}}}{tag_name}')
        if elemento is not None:
            return elemento
    
    # Tenta caminhos específicos
    for path in paths:
        elemento = root.find(path)
        if elemento is not None:
            return elemento
        
        # Tenta caminho com namespace
        for ns in namespaces.values():
            # Substitui tags no path por tags com namespace
            path_com_ns = path
            for tag in re.findall(r'([A-Za-z][A-Za-z0-9]*)', path):
                path_com_ns = path_com_ns.replace(f'/{tag}', f'/{{{ns}}}{tag}')
            elemento = root.find(path_com_ns)
            if elemento is not None:
                return elemento
    
    return None

def analisar_servicos_xml(arquivos_xml):
    """
    Analisa arquivos XML e extrai informações de cada nota individualmente:
    - Número da nota
    - Valor (BaseCalculo)
    - Descrição (Discriminacao)
    """
    resultados = []
    
    for arquivo in arquivos_xml:
        try:
            tree = ET.parse(arquivo)
            root = tree.getroot()
            
            # Registra os namespaces encontrados
            namespaces = {}
            if '}' in root.tag:
                ns_url = root.tag.split('}')[0].strip('{')
                namespaces['ns'] = ns_url
            
            # Busca o número da nota
            numero = None
            paths_numero = [
                './/Numero',
                './/InfNfse/Numero',
                './/IdentificacaoNfse/Numero',
                './/Nfse/InfNfse/Numero'
            ]
            elem_numero = buscar_tag_xml(root, 'Numero', namespaces, paths_numero)
            if elem_numero is not None and elem_numero.text:
                numero = elem_numero.text.strip()
            
            # Busca o valor (BaseCalculo dentro de ValoresNfse)
            valor = None
            # Primeiro tenta buscar diretamente BaseCalculo
            paths_base_calculo = [
                './/BaseCalculo',
                './/ValoresNfse/BaseCalculo',
                './/InfNfse/ValoresNfse/BaseCalculo',
                './/Nfse/InfNfse/ValoresNfse/BaseCalculo',
                './/Servico/Valores/BaseCalculo'
            ]
            elem_valor = buscar_tag_xml(root, 'BaseCalculo', namespaces, paths_base_calculo)
            
            # Se não encontrou, tenta buscar primeiro ValoresNfse e depois BaseCalculo dentro dele
            if elem_valor is None:
                paths_valores_nfse = [
                    './/ValoresNfse',
                    './/InfNfse/ValoresNfse',
                    './/Nfse/InfNfse/ValoresNfse',
                    './/Servico/Valores'
                ]
                elem_valores = buscar_tag_xml(root, 'ValoresNfse', namespaces, paths_valores_nfse)
                
                if elem_valores is not None:
                    # Busca BaseCalculo dentro de ValoresNfse encontrado
                    elem_valor = elem_valores.find('.//BaseCalculo')
                    if elem_valor is None:
                        for ns in namespaces.values():
                            elem_valor = elem_valores.find(f'.//{{{ns}}}BaseCalculo')
                            if elem_valor is not None:
                                break
                    # Se ainda não encontrou, tenta buscar como filho direto
                    if elem_valor is None:
                        elem_valor = elem_valores.find('BaseCalculo')
                        if elem_valor is None:
                            for ns in namespaces.values():
                                elem_valor = elem_valores.find(f'{{{ns}}}BaseCalculo')
                                if elem_valor is not None:
                                    break
            
            if elem_valor is not None and elem_valor.text:
                valor_texto = elem_valor.text.strip()
                # Formata valor numérico
                try:
                    valor_float = float(valor_texto.replace(',', '.'))
                    valor = f"{valor_float:.2f}".replace('.', ',')
                except:
                    valor = valor_texto
            
            # Busca a descrição (Discriminacao)
            descricao = None
            paths_discriminacao = [
                './/Discriminacao',
                './/Servico/Discriminacao',
                './/InfDeclaracaoPrestacaoServico/Servico/Discriminacao',
                './/DeclaracaoPrestacaoServico//Discriminacao',
                './/Nfse/InfNfse/Servico/Discriminacao'
            ]
            elem_disc = buscar_tag_xml(root, 'Discriminacao', namespaces, paths_discriminacao)
            
            if elem_disc is not None and elem_disc.text:
                descricao_texto = limpar_texto_servico(elem_disc.text.strip())
                descricao = descricao_texto if descricao_texto else None
            
            # Adiciona resultado (nota individual)
            resultados.append({
                'Arquivo': os.path.basename(arquivo.name),
                'Numero_Nota': numero if numero else 'Não encontrado',
                'Valor': valor if valor else 'Não encontrado',
                'Descricao': descricao if descricao else 'Não encontrado'
            })
            
        except Exception as e:
            resultados.append({
                'Arquivo': os.path.basename(arquivo.name),
                'Numero_Nota': f'Erro: {str(e)}',
                'Valor': '',
                'Descricao': ''
            })
    
    return pd.DataFrame(resultados)

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
st.set_page_config(page_title="Análise de Serviço", layout="wide")

# Criação de abas para diferentes funcionalidades
tab1, tab2 = st.tabs(["Análise XML", "Correção PDF"])

with tab1:
    st.title("Análise de Notas Fiscais XML")
    st.markdown("Extrai **Número**, **Valor** e **Descrição** de cada nota fiscal individualmente.")
    arquivos_upload = st.file_uploader("Selecione os arquivos XML ou ZIP", type=['xml', 'zip'], accept_multiple_files=True)

    if arquivos_upload and st.button("Analisar XML"):
        arquivos_xml, temp_dirs = processar_arquivos(arquivos_upload)
        
        if arquivos_xml:
            with st.spinner("Processando arquivos XML..."):
                df = analisar_servicos_xml(arquivos_xml)
            
            st.success(f"✅ {len(df)} nota(s) processada(s) com sucesso!")
            
            # Exibe a tabela com os resultados
            st.dataframe(df, use_container_width=True)
            
            # Botão para download dos resultados em CSV
            csv = df.to_csv(index=False, encoding='utf-8-sig')
            st.download_button(
                label="📥 Baixar resultados em CSV",
                data=csv,
                file_name="notas_fiscais_analise.csv",
                mime="text/csv"
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
    st.title("Correção de PDFs")
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
