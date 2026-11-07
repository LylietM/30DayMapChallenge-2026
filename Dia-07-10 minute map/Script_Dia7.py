from qgis.PyQt.QtCore import QVariant
from qgis.core import QgsProject, QgsField
import processing
 
# 1. LOCALIZAR LAS CAPAS (una sola vez)
capa = QgsProject.instance().mapLayersByName('MallaUTM1x1')[0]
presencias = QgsProject.instance().mapLayersByName('presenciasTrepador')[0]
 
if not capa.isValid() or not presencias.isValid():
    raise Exception("Alguna de las capas no es válida.")
 
# 2. SELECCIONAR LAS CELDAS QUE INTERSECTAN CON LAS PRESENCIAS
processing.run("native:selectbylocation", {'INPUT': capa,'PREDICATE': [0],
    'INTERSECT': presencias,'METHOD': 0})
 
# 3. GUARDAR LOS IDs SELECCIONADOS
ids_con_presencia = set(capa.selectedFeatureIds())
 
# 4. EDITAR: CREAR EL CAMPO PRESENCIAS
capa.startEditing()
 
if capa.fields().indexOf("presencias") == -1:
    capa.addAttribute(QgsField("presencias", QVariant.Int))
    capa.updateFields()
 
indice_campo = capa.fields().indexOf("presencias")
 
# 5. ASIGNAR 1 A LAS CELDAS SELECCIONADAS Y 0 A LAS DEMÁS
for objeto in capa.getFeatures():
    valor = 1 if objeto.id() in ids_con_presencia else 0
    capa.changeAttributeValue(objeto.id(), indice_campo, valor)
 
# 6. GUARDAR CAMBIOS Y LIMPIAR LA SELECCIÓN
if capa.commitChanges():
    capa.removeSelection()
    print(f"Hecho: {len(ids_con_presencia)} celdas con presencia = 1.")
else:
    print("Error al guardar:", capa.commitErrors())
 