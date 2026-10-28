"""Validación y combinación del detalle; no escribe en la base."""
from decimal import Decimal


def consolidate(lines):
    if not lines:
        raise ValueError('Agrega al menos un producto')
    result={}
    for source in lines:
        line={k:v for k,v in source.items() if k!='source_index'}
        q=Decimal(str(line['cantidad']));c=Decimal(str(line['costo_unitario']))
        if not q.is_finite() or not c.is_finite() or q<=0 or c<0:
            raise ValueError('Cantidad o costo inválido')
        if not str(line.get('codigo_de_barras') or '').strip():
            raise ValueError('Completa los códigos de barras antes de guardar')
        key=line['producto_id']
        if key in result:
            previous=result[key]
            if bool(previous['nuevo'])!=bool(line['nuevo']) or previous['codigo_de_barras']!=line['codigo_de_barras']:
                raise ValueError('Un producto tiene códigos o vínculos incompatibles')
            old_q=Decimal(str(previous['cantidad']));old_c=Decimal(str(previous['costo_unitario']))
            previous['costo_unitario']=str((old_q*old_c+q*c)/(old_q+q))
            previous['cantidad']=str(old_q+q)
        else:
            line['cantidad']=str(q);line['costo_unitario']=str(c)
            result[key]=line
    barcodes={}
    for key,line in result.items():
        code=line['codigo_de_barras']
        if code in barcodes and barcodes[code]!=key:
            raise ValueError('El mismo código de barras está vinculado a dos productos distintos')
        barcodes[code]=key
    return list(result.values())
