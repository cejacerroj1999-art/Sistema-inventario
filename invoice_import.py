                found['cost'] = w['x0']
            elif t in ('und', 'unidad', 'u/m'):
                found['unit'] = w['x0']
            elif t.startswith(('impto', 'impuesto')):
                found['tax'] = w['x0']
            elif t.startswith(('desc', 'descuento')) and t != 'descripcion':
                found['discount'] = w['x0']
            elif t in ('valor', 'subtotal', 'sub-total', 'importe'):
                found['amount'] = w['x0']
        if {'name', 'qty', 'cost'} <= found.keys():
            header, header_index = found, i
            break
    if header is None:
        return []

    qty_start = header['qty'] - 17
    following_qty = [x for k,x in header.items() if x > header['qty'] and k != 'amount']
    qty_end = min(following_qty) - 8 if following_qty else header['cost'] - 10
    cost_start = header['cost'] - 16
    following_cost = [x for k,x in header.items() if x > header['cost']]
    cost_end = min(following_cost) - 7 if following_cost else page.width
    amount_start = header.get('amount', page.width + 1) - 18
    output = []
    pending = ''
    for row in rows[header_index+1:]:
        ws = row['words']
        line = norm(' '.join(w['text'] for w in ws))
        if re.match(r'^(?:documento referencia|timbre electronico|subtotal|total neto|monto neto|observaciones|descto\.|neto afecto)\b', line):
            break
        qty_words = [w['text'] for w in ws if qty_start <= w['x0'] < qty_end]
        cost_words = [w['text'] for w in ws if cost_start <= w['x0'] < cost_end]
        desc_words = [w['text'] for w in ws if w['x0'] < qty_start]
        amount_words = [w['text'] for w in ws if w['x0'] >= amount_start]
        if not qty_words or not cost_words:
            if desc_words and not any(w['text'].lower() in ('codigo','descripcion') for w in ws):
                pending += ' ' + ' '.join(desc_words)
            continue
        try:
            qty = money(''.join(qty_words))
            cost = money(cost_words[0])  # El primer valor es el precio; otros pueden ser impuestos/descuentos
            if qty <= 0 or qty != qty.to_integral_value() or cost <= 0:
                continue
            if amount_words:
                try:
                    amount = money(''.join(amount_words))
                    if abs(cost * qty - amount) > Decimal('1.01'):
                        cost = amount / qty
                except ValueError:
                    pass
        except ValueError:
            continue
        if not desc_words:
            continue
        code = desc_words[0] if 'code' in header else ''
        name = ' '.join(desc_words[1:] if code else desc_words).strip()
        if pending.strip():
            name = (pending.strip() + ' ' + name).strip()
            pending = ''
        if not name:
            continue
        output.append(dict(nombre=name, cantidad=int(qty), costo_unitario=float(cost),
                           codigo_de_barras=''))
    return output


def _ocr(image):
    import pytesseract
    try:
        return pytesseract.image_to_string(image,lang='spa',timeout=45)
    except (pytesseract.TesseractNotFoundError,pytesseract.TesseractError,RuntimeError) as exc:
        raise ValueError('No fue posible ejecutar OCR. Verifica packages.txt y la instalación de tesseract-ocr-spa en Streamlit.') from exc



def read_invoice(data, filename):
    """Lee PDF (todas las páginas), XML o imagen. Revisa duplicados de copias."""
    if len(data) > 15 * 1024 * 1024:
        raise ValueError('El archivo supera 15 MB')
    if filename.lower().endswith('.xml'):
        return read_xml(data)
    texts, lines, warnings = [], [], []
    if data.startswith(b'%PDF-'):
        import pdfplumber
        with pdfplumber.open(BytesIO(data)) as pdf:
            if not pdf.pages:
                raise ValueError('El PDF no contiene páginas')
            signatures = set()
            for n, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ''
                if len(text.strip()) < 30:
                    pixels = page.width * page.height * (150 / 72) ** 2
                    if pixels > 30_000_000:
                        raise ValueError('La página es demasiado grande para OCR')
                    text = _ocr(page.to_image(resolution=150).original)
                texts.append(text)
                candidates = pdf_product_lines(page)
                if not candidates:
                    for table in page.extract_tables():
                        candidates.extend(table_lines(table))
                if not candidates:
                    candidates = text_lines(text)
                # No deduplicar productos dentro de la misma página: podrían ser líneas legítimas.
                signature = tuple((norm(x['nombre']), str(x['cantidad']),
                                   round(float(x['costo_unitario']), 2)) for x in candidates)
                if signature and signature in signatures:
                    warnings.append(f'Página {n}: copia de detalle ya procesado; no se duplicaron unidades.')
                    continue
                if signature:
                    signatures.add(signature)
                lines.extend(candidates)
                if not candidates:
                    warnings.append(f'Página {n}: no se detectaron productos; revisar manualmente.')
    else:
        from PIL import Image, ImageOps
        with Image.open(BytesIO(data)) as original:
            if original.width * original.height > 30_000_000:
                raise ValueError('La imagen supera 30 megapíxeles')
            image = ImageOps.exif_transpose(original).convert('RGB')
            text = _ocr(image)
            texts.append(text)
            lines = text_lines(text)
    result = metadata('\n'.join(texts))
    result.lines = lines
    result.warnings.extend(warnings)
    if not lines:
        result.warnings.append('No se reconocieron productos; ingrésalos manualmente antes de guardar.')
    result.warnings.append('Revisa cantidades y costos con la factura antes de registrar.')
    return result
