import pdfplumber, re, os

files = ['certificates/10002000000255.pdf', 'certificates/10002000000287.pdf', 'certificates/10003000000190.pdf']

for f in files:
    if not os.path.exists(f):
        print(f'{f} - FILE NOT FOUND')
        continue
    with pdfplumber.open(f) as pdf:
        text = pdf.pages[0].extract_text() or ''
        if len(pdf.pages) > 1:
            text += pdf.pages[1].extract_text() or ''
        print(f'\n=== {f} ===')
        print(text[:600])
        rera = re.search(r'WBRERA[/\s]*[A-Z]+[/\s]*\d+[/\s]*\d+', text)
        print('RERA:', rera.group(0) if rera else 'NOT FOUND')