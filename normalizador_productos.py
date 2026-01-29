"""
Normalizador de jerga y variantes para productos de seguridad.
"""

import re

MARCAS_VARIANTES = {
    'hikvision': [
        'hik', 'hikv', 'hikvision', 'hikvisio', 'hikvicion',
        'hikvison', 'hikivision', 'hikvition', 'hkvision',
        'hikvisión', 'hikvisionn', 'hikvizion', 'hikvi'
    ],
    'dahua': [
        'dau', 'daua', 'dauha', 'dahua', 'dahu', 'dahuaa',
        'dawua', 'dauhua', 'dahuwa', 'dahúa', 'dawa'
    ],
    'ajax': [
        'ajax', 'ajaz', 'ayax', 'ajacs', 'ajx', 'ajas'
    ],
    'intelbras': [
        'intelbras', 'intelbra', 'intelbrass', 'intelbraz',
        'intelbrás', 'intelbrs', 'intelbas', 'intelb'
    ],
    'dsc': ['dsc', 'dcs', 'dscpower'],
    'ubiquiti': [
        'ubiquiti', 'ubiquity', 'ubikiti', 'ubnt', 'unifi',
        'ubiquitti', 'ubiqiti', 'ubiquiri'
    ],
    'zkteco': [
        'zkteco', 'zk', 'zktek', 'zktec', 'zkteko'
    ],
    'paradox': [
        'paradox', 'paradx', 'paradoj', 'paradocs', 'parado'
    ],
    'honeywell': [
        'honeywell', 'honeywel', 'honeywall', 'honey'
    ],
    'epcom': ['epcom', 'epcpm', 'epcon', 'epcm'],
    'bosch': ['bosch', 'bosh', 'bosc', 'boch'],
    'ezviz': ['ezviz', 'ezbiz', 'esviz', 'ezvizz'],
    'imou': ['imou', 'imu', 'imuo', 'imo'],
    'reyee': ['reyee', 'reye', 'reyeee', 'reyi'],
    'ruijie': ['ruijie', 'ruiji', 'ruiie', 'rujie'],
    'alean': ['alean', 'alea', 'aleaan'],
    'cygnus': ['cygnus', 'cignus', 'cygns', 'cigno'],
    'tp-link': ['tplink', 'tp-link', 'tp link', 'tplnk'],
    'mikrotik': ['mikrotik', 'mikrotick', 'mikrotk', 'microtik'],
    'seco-larm': ['secolarm', 'seco-larm', 'seco larm', 'secolam'],
}

PRODUCTOS_VARIANTES = {
    'camara': [
        'camara', 'cámara', 'camaras', 'cámaras', 'cam',
        'camera', 'kamara', 'cmara', 'camra', 'cammara'
    ],
    'domo': ['domo', 'dome', 'domos', 'domes', 'dom', 'dommo'],
    'bullet': [
        'bullet', 'bala', 'balas', 'bullets', 'bulet', 'buller'
    ],
    'ptz': [
        'ptz', 'robotica', 'robotizada', 'robótica',
        'speeddome', 'speedome', 'pzt', 'pttz'
    ],
    'turret': ['turret', 'torreta', 'torret', 'turet', 'turrent'],
    'dvr': [
        'dvr', 'dvrs', 'grabador', 'grabadora', 'deveerre',
        'dvvr', 'dvrr', 'gravador'
    ],
    'nvr': ['nvr', 'nvrs', 'eneverr', 'nvrr', 'nvvr', 'nevr'],
    'xvr': ['xvr', 'xvrr', 'hibrido', 'híbrido', 'pentahibrido'],
    'alarma': [
        'alarma', 'alarmas', 'alarm', 'alrma', 'alarrma', 'alarmma'
    ],
    'central': ['central', 'centrales', 'sentral', 'panel'],
    'kit': ['kit', 'kits', 'combo', 'combos', 'conjunto', 'paquete'],
    'teclado': ['teclado', 'teclados', 'keypad', 'keypads', 'teclao'],
    'sirena': ['sirena', 'sirenas', 'bocina', 'chicharra', 'sirema'],
    'sensor': ['sensor', 'sensores', 'sens', 'censor', 'sencor'],
    'pir': [
        'pir', 'infrarrojo', 'movimiento', 'movimento', 'infrarojo'
    ],
    'magnetico': [
        'magnetico', 'magnético', 'magneticos', 'mag', 'magnet',
        'imán', 'iman', 'contacto'
    ],
    'humo': ['humo', 'humos', 'smoke', 'detector humo'],
    'cortina': ['cortina', 'curtain', 'cortinas', 'curtan'],
    'motionprotect': [
        'motionprotect', 'motion protect', 'motion-protect',
        'mocionprotect', 'motionprotec', 'motionpro'
    ],
    'doorprotect': [
        'doorprotect', 'door protect', 'door-protect',
        'dorprotect', 'doorprotec', 'doorpro'
    ],
    'axpro': [
        'axpro', 'ax pro', 'ax-pro', 'axpror', 'ax prro', 'axp'
    ],
    'hubpro': ['hubpro', 'hub pro', 'hub-pro', 'hubp'],
    'hub2': ['hub2', 'hub 2', 'hub-2', 'hubdos', 'hub dos'],
    'dualcurtain': [
        'dualcurtain', 'dual curtain', 'dualcurtian',
        'dual cortina', 'curtain dual'
    ],
    'combiprotect': ['combiprotect', 'combi protect', 'combi'],
    'leaksprotect': ['leaksprotect', 'leaks protect', 'leak'],
    'fireprotect': ['fireprotect', 'fire protect', 'fuego ajax'],
    'amt': ['amt', 'amtt'],
    'amt4010': [
        'amt4010', 'amt 4010', 'amt-4010', '4010',
        'amt4010smart', '4010smart', '4010 smart'
    ],
    'amt8000': [
        'amt8000', 'amt 8000', 'amt-8000', '8000',
        'amt8000smart', '8000smart', '8000 smart'
    ],
    'disco': [
        'disco', 'discos', 'hdd', 'hd', 'rigido', 'rígido',
        'almacenamiento', 'disko', 'dicso', 'dicsco'
    ],
    'purple': ['purple', 'purpel', 'violeta', 'purpura', 'vigilancia'],
    'skyhawk': ['skyhawk', 'sky hawk', 'skyhak', 'skyhauk'],
    'cable': ['cable', 'cables', 'cableado', 'cble', 'cabl'],
    'utp': ['utp', 'utpp', 'ethernet', 'cat5', 'cat6', 'cat5e'],
    'coaxil': ['coaxil', 'coaxial', 'coaxi', 'coax', 'rg59', 'rg6'],
    'fuente': [
        'fuente', 'fuentes', 'power', 'alimentacion',
        'alimentación', 'transformador', 'trafo', 'fente'
    ],
    'ups': ['ups', 'upss', 'bateria', 'batería', 'respaldo'],
    'biometrico': [
        'biometrico', 'biométrico', 'huella', 'fingerprint'
    ],
    'facial': ['facial', 'rostro', 'face', 'reconocimientofacial'],
    'switch': [
        'switch', 'switches', 'suich', 'suitch', 'swich', 'swicth'
    ],
    'router': ['router', 'routers', 'ruter', 'ruteador', 'roter'],
    'balun': ['balun', 'baluns', 'balum', 'balon', 'video balun'],
    'videoportero': [
        'videoportero', 'video portero', 'portero visor',
        'citofono', 'intercomunicador', 'intercom'
    ],
    'cerco': [
        'cerco', 'cercos', 'cercoelectrico', 'electrificador',
        'cerca', 'cerco eléctrico'
    ],
    'conector': ['conector', 'conectores', 'bnc', 'conect'],
    'gabinete': ['gabinete', 'gabinetes', 'caja', 'cajas', 'rack'],
    'soporte': ['soporte', 'soportes', 'brazo', 'brazos', 'mount'],
    'inyector': ['inyector', 'inyectores', 'inyector poe'],
}

CODIGOS_VARIANTES = {
    'ds-2cd': ['ds2cd', 'ds 2cd', 'ds-2cd', 'ds2 cd'],
    'ds-7': ['ds7', 'ds 7', 'ds-7'],
    'ds-k': ['dsk', 'ds k', 'ds-k'],
    'ds-2ce': ['ds2ce', 'ds 2ce', 'ds-2ce'],
    'dh-': ['dh', 'dh-', 'dh '],
    'ipc-': ['ipc', 'ipc-', 'ipc '],
    'hac-': ['hac', 'hac-', 'hac '],
    'amt4010': [
        'amt4010', 'amt 4010', 'amt-4010', '4010smart',
        '4010 smart', 'amt4010smart', 'amt 4010 smart'
    ],
    'amt8000': [
        'amt8000', 'amt 8000', 'amt-8000', 'amt 8000 smart'
    ],
    'hub2plus': [
        'hub2plus', 'hub 2 plus', 'hub2 plus', 'hub-2-plus'
    ],
}


def normalizar_busqueda(texto):
    if not texto:
        return ""

    resultado = texto.lower().strip()

    # Normalizar marcas
    for marca_correcta, variantes in MARCAS_VARIANTES.items():
        for variante in variantes:
            pattern = r'\b' + re.escape(variante) + r'\b'
            if re.search(pattern, resultado):
                resultado = re.sub(pattern, marca_correcta, resultado)

    # Normalizar productos
    for prod_correcto, variantes in PRODUCTOS_VARIANTES.items():
        for variante in variantes:
            pattern = r'\b' + re.escape(variante) + r'\b'
            if re.search(pattern, resultado):
                resultado = re.sub(pattern, prod_correcto, resultado)

    # Normalizar códigos (por longitud, más largo primero)
    todas = []
    for cod, vars in CODIGOS_VARIANTES.items():
        for v in vars:
            todas.append((v, cod))
    todas.sort(key=lambda x: len(x[0]), reverse=True)

    for variante, correcto in todas:
        if variante in resultado:
            resultado = resultado.replace(variante, correcto, 1)
            break

    resultado = re.sub(r'\s+', ' ', resultado).strip()
    return resultado


def obtener_variantes_busqueda(texto):
    variantes = [texto.lower().strip()]

    sin_espacios = texto.replace(' ', '')
    if sin_espacios not in variantes:
        variantes.append(sin_espacios)

    con_guion = texto.replace(' ', '-')
    if con_guion not in variantes:
        variantes.append(con_guion)

    normalizado = normalizar_busqueda(texto)
    if normalizado not in variantes:
        variantes.append(normalizado)

    norm_sin_esp = normalizado.replace(' ', '')
    if norm_sin_esp not in variantes:
        variantes.append(norm_sin_esp)

    return variantes
