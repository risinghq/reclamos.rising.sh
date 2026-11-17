import re

from reclamos_api.cases.brands import BRANDS
from reclamos_api.outcomes.source import plain

BILLING = "facturación y cobro"
QUALITY = "calidad del servicio"
NO_SERVICE = "falta de servicio"
CANCELLATION = "baja o suspensión no atendida"
UNREQUESTED = "contratación no solicitada"
CONTRACT = "condiciones del contrato, ofertas y promociones"
OTHER_MATTERS = "otras materias reclamables"
NO_ANSWER = "falta de respuesta al reclamo"
PROCEDURE = "otros defectos del trámite"
SUSPENDED = "suspensión con reclamo en trámite"
NOT_ACCEPTED = "no se permitió presentar el reclamo, recurso o queja"
PAYMENT_DEMANDED = "cobro del monto reclamado"
PARTIAL_PAYMENT = "no se permitió pagar a cuenta"
TOP_UPS = "recargas y saldo"
INSTALLATION = "instalación, activación o traslado"
HANDSET_LOCK = "bloqueo o desbloqueo de equipo"
HOLDER = "cambio de titularidad"
RULINGS = "incumplimiento de resoluciones"
RECEIPT = "falta de entrega del recibo"

CONCEPTS: dict[str, str] = {
    "FACTURACIÓN": BILLING,
    "FACTURACIÓN Y COBRO": BILLING,
    "COBRO": BILLING,
    "REINTEGRO DE EQUIPO": BILLING,
    "CALIDAD": QUALITY,
    "CALIDAD E IDONEIDAD EN LA PRESTACIÓN DEL SERVICIO": QUALITY,
    "IDONEIDAD": QUALITY,
    "FALTA DE SERVICIO": NO_SERVICE,
    "SUSPENSIÓN": NO_SERVICE,
    "CORTE O BAJA DEL SERVICIO": NO_SERVICE,
    "CORTE": NO_SERVICE,
    "BAJA INJUSTIFICADA DEL SERVICIO": NO_SERVICE,
    "FALTA DE EJECUCIÓN DE BAJA O SUSPENSIÓN": CANCELLATION,
    "BAJA NO ATENDIDA": CANCELLATION,
    "BAJA": CANCELLATION,
    "SOLICITUD DE BAJA DE SERVICIO NO ATENDIDA": CANCELLATION,
    "CONTRATACIÓN NO SOLICITADA": UNREQUESTED,
    "DESCONOCIMIENTO DE CONTRATACIÓN": UNREQUESTED,
    "INCUMPLIMIENTO DE CONDICIONES CONTRACTUALES, OFERTAS Y PROMOCIONES": CONTRACT,
    "INCUMPLIMIENTO DE CONDICIONES CONTRACTUALES": CONTRACT,
    "INCUMPLIMIENTO DE OFERTAS Y PROMOCIONES VINCULADAS A LA PRESTACIÓN DEL "
    "SERVICIO PÚBLICO DE TELECOM": CONTRACT,
    "VERACIDAD DE LA INFORMACIÓN": CONTRACT,
    "OTRAS MATERIAS RECLAMABLES": OTHER_MATTERS,
    "CUALQUIER MATERIA RELACIONADA DIRECTAMENTE CON LA PRESTACIÓN DEL SERV. PUB. "
    "DE TELECOM. CONTRATADO": OTHER_MATTERS,
    "OTROS QUE SEÑALE EL CONSEJO DIRECTIVO": OTHER_MATTERS,
    "FALTA DE RESPUESTA AL RECLAMO": NO_ANSWER,
    "NO CONTESTACIÓN OPORTUNA": NO_ANSWER,
    "INFRACCIÓN DE PLAZOS": NO_ANSWER,
    "OTROS DEFECTOS DE TRAMITACIÓN": PROCEDURE,
    "OTRAS TRANSGRESIONES DEL PROCEDIMIENTO": PROCEDURE,
    "NO ELEVACIÓN": PROCEDURE,
    "NO PERMITIR ACCESO AL EXPEDIENTE": PROCEDURE,
    "SUSPENSIÓN DEL SERVICIO PESE A RECLAMO EN TRÁMITE": SUSPENDED,
    "SUSPENSIÓN DEL SERVICIO CON RECLAMO EN TRÁMITE": SUSPENDED,
    "NO REACTIVACIÓN ANTE RECLAMO, RECONSIDERACIÓN, RA O RQJ": SUSPENDED,
    "NO SE PERMITIÓ LA PRESENTACIÓN DE RECLAMO, RECURSO DE APELACIÓN O QUEJA O "
    "NO SE OTORGO EL CÓDIGO RESPECTIVO": NOT_ACCEPTED,
    "NO PERMITIR LA PRESENTACIÓN DE UN RECURSO O QUEJA": NOT_ACCEPTED,
    "NO PERMITIR LA PRESENTACIÓN DE UN RECLAMO": NOT_ACCEPTED,
    "NO BRINDAR CÓDIGO DE RECLAMO, RECURSO O QUEJA": NOT_ACCEPTED,
    "REQUERIMIENTO DE PAGO DEL MONTO RECLAMADO": PAYMENT_DEMANDED,
    "REQUERIMIENTO DE PAGO CON RECLAMO EN TRÁMITE": PAYMENT_DEMANDED,
    "NO SE PERMITIO PAGO A CUENTA DEL MONTO NO RECLAMADO": PARTIAL_PAYMENT,
    "NO PERMITE PAGO A CUENTA": PARTIAL_PAYMENT,
    "RECARGAS": TOP_UPS,
    "PROBLEMAS CON TARJETAS DE PAGO FÍSICAS O VIRTUALES": TOP_UPS,
    "TARJETAS PRE-PAGO": TOP_UPS,
    "RECARGA NO PROCESADA": TOP_UPS,
    "DESCUENTO DE SALDO": TOP_UPS,
    "ASIGNACION DE SALDO": TOP_UPS,
    "ASIGNACION DE MINUTOS": TOP_UPS,
    "INSTALACIÓN, ACTIVACIÓN O TRASLADO": INSTALLATION,
    "INSTALACIÓN": INSTALLATION,
    "ACTIVACIÓN": INSTALLATION,
    "TRASLADO": INSTALLATION,
    "DESBLOQUEO/BLOQUEO DE EQUIPO": HANDSET_LOCK,
    "DESBLOQUEO DE EQUIPO": HANDSET_LOCK,
    "CAMBIO DE TITULARIDAD": HOLDER,
    "CAMBIO DE TITULARIDAD NO SOLICITADA": HOLDER,
    "INCUMPLIMIENTO DE RES. DE EO": RULINGS,
    "INCUMPL. DE RES. DEL TRIB.": RULINGS,
    "FALTA DE ENTREGA DEL RECIBO O DE LA COPIA": RECEIPT,
    "FALTA DE ENTREGA DE LA FACTURACIÓN DETALLADA": RECEIPT,
    "MATERIA NO RECLAMABLE": "materia no reclamable",
    "MIGRACIÓN": "migración de plan",
    "PORTABILIDAD": "portabilidad",
    "NEGATIVA A CONTRATAR": "negativa a contratar",
    "INDEMNIZACIÓN": "indemnización",
    "TARIFAS": "tarifas",
    "INCUMPLIMIENTO DE DERECHOS RECONOCIDOS EN LA NORMATIVA DE USUARIOS DE "
    "SERV. PUB. DE TELECOM.": "derechos de los usuarios",
    "FRACCIONAMIENTO - EMERGENCIA SANITARIA": "fraccionamiento en la emergencia sanitaria",
    "NO ATENCIÓN DE SOLICITUD DE COPIAS": "copias no entregadas",
    "COMPENSACIÓN POR INTERRUPCIÓN": "compensación por interrupción",
    "NO BRINDAR INFORMACION DE PLAZOS DE PROCEDIMIENTO": "información sobre plazos",
    "NO PERMITIR LA PRESENTACIÓN DE UN REPORTE": "no se permitió presentar un reporte",
}

NO_DETAIL = "NO APLICA"

OUTCOMES: dict[str, str] = {
    "FUNDADO": "fundado",
    "PARCIALMENTE FUNDADO": "fundado_en_parte",
    "INFUNDADO": "infundado",
    "IMPROCEDENTE": "improcedente",
}
OTHER = "other"
OUTCOME_KEYS = (*OUTCOMES.values(), OTHER)

_CONCEPTS = {plain(label): concept for label, concept in CONCEPTS.items()}


def _company(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", re.sub(r"\(.*?\)", "", plain(name)))


_COMPANIES = {
    _company(name): brand for brand, names in BRANDS.items() for name in names
}


def brand_of_company(company: str) -> str | None:
    return _COMPANIES.get(_company(company))


def concept_of(concepto: str) -> str | None:
    return _CONCEPTS.get(plain(concepto))


def detail_key(subconcepto: str) -> str:
    key = plain(subconcepto)
    return "" if key == NO_DETAIL else key


def detail_text(subconcepto: str) -> str:
    return " ".join(
        "empresa operadora" if word == "eo" else word
        for word in subconcepto.lower().split()
    )


def outcome_of(sentido: str) -> str:
    return OUTCOMES.get(sentido, OTHER)
