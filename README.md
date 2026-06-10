# 🚗 MeLi Autos — Buscador de Oportunidades

Busca vehículos e inmuebles en MercadoLibre Colombia y detecta automáticamente las mejores oportunidades de negocio usando análisis de precios, kilometraje y señales del vendedor.

## Características

- Búsqueda en Carros, Motos, Camiones, Casas, Apartamentos, Fincas, Bodegas
- Puntaje de oportunidad 0-100 por vehículo
- Detección de: precio bajo la mediana, bajo km, único dueño, negociable, urgencia
- Pantalla de inicio con mejores oportunidades del momento
- Análisis IA de descripciones (opcional, requiere API key de Anthropic)

## Instalación local

```bash
pip install -r requirements.txt
python app.py
```

Abrir: http://localhost:5000

## Deploy en Railway

1. Fork este repositorio
2. Conectar en railway.app con el repo
3. Railway detecta el Dockerfile automáticamente
4. Deploy 🚀
