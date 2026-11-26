// 1. Area de estudio en La Albuera, Badajoz
var roi = ee.Geometry.Polygon([[
  [-6.83, 38.74],
  [-6.72, 38.74],
  [-6.72, 38.66],
  [-6.83, 38.66]
]]);

// Calculo de NDWI = (B3 - B8) / (B3 + B8)
function addNDWI(img) {
  var ndwi = img.normalizedDifference(['B3', 'B8']).rename('NDWI');
  return img.addBands(ndwi);
}

// 2. EPOCA SECA (julio - septiembre 2025)
var dryCol = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
  .filterBounds(roi)
  .filterDate('2025-07-15', '2025-09-15')
  .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 25))
  .map(addNDWI);

// 3. MAYOR NIVEL / EPOCA HUMEDA (febrero-abril)
var wetCol = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
  .filterBounds(roi)
  .filterDate('2025-02-01', '2025-04-30')
  .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 10))
  .map(addNDWI);
  
// Compuestos de cada periodo
var dryImg = dryCol.median().clip(roi);
var wetImg = wetCol.select('NDWI').max().clip(roi)
  .addBands(wetCol.median().clip(roi).select(['B4', 'B3', 'B2']));

// Umbral para aislar agua
var waterThreshold = 0.05;

// Nos quedamos solo con los pixeles de NDWI por encima del umbral
var dryWaterNDWI = dryImg.select('NDWI').updateMask(dryImg.select('NDWI').gt(waterThreshold));
var wetWaterNDWI = wetImg.select('NDWI').updateMask(wetImg.select('NDWI').gt(waterThreshold));

// Parametros de visualizacion
var rgbVis = {bands: ['B4', 'B3', 'B2'], min: 200, max: 2500};
// Paleta solo para zonas de agua
var waterNdwiVis = {
  min: 0.05,
  max: 0.5,
  palette: ['#7DD3FC', '#0284C7', '#1E3A8A']
};

// 4. Dos mapas vinculados para el deslizador (izquierda = seca, derecha = mayor nivel)
var leftMap = ui.Map();
var rightMap = ui.Map();

leftMap.setControlVisibility({layerList: true, zoomControl: true, fullscreenControl: false});
rightMap.setControlVisibility({layerList: true, zoomControl: false, fullscreenControl: false});

leftMap.add(ui.Label('ÉPOCA MENOR PRECIPITACIÓN', {position: 'top-left', fontWeight: 'bold'}));
rightMap.add(ui.Label('ÉPOCA MAYOR PRECIPITACIÓN', {position: 'top-right', fontWeight: 'bold'}));

leftMap.addLayer(dryImg, rgbVis, 'Satélite RGB - Seca', true);
leftMap.addLayer(dryWaterNDWI, waterNdwiVis, 'NDWI Agua - Seca', true);

rightMap.addLayer(wetImg, rgbVis, 'Satélite RGB - Mayor nivel', true);
rightMap.addLayer(wetWaterNDWI, waterNdwiVis, 'NDWI Agua - Mayor nivel', true);

// Vincular ambos mapas para mantener el mismo encuadre y zoom
ui.Map.Linker([leftMap, rightMap]);

// 5. Panel unico con barra deslizante horizontal (wipe: true)
var swipePanel = ui.SplitPanel({
  firstPanel: leftMap,
  secondPanel: rightMap,
  wipe: true,
  style: {stretch: 'both'}
});

ui.root.widgets().reset([swipePanel]);
leftMap.centerObject(roi, 13);