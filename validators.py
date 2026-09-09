import re


def validar_cuit(cuit) -> bool:
    if not cuit:
        return False
    digits = re.sub(r"\D", "", str(cuit))
    if len(digits) != 11:
        return False

    multiplicadores = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    suma = sum(int(d) * m for d, m in zip(digits[:10], multiplicadores))
    resto = suma % 11

    if resto == 0:
        verificador = 0
    elif resto == 1:
        return False
    else:
        verificador = 11 - resto

    return verificador == int(digits[10])
