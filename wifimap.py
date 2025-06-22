import osmnx as ox
import pandas as pd
import folium
import streamlit as st
from streamlit_folium import st_folium
from geopy.distance import geodesic
from folium.plugins import PolyLineTextPath
import networkx as nx

st.set_page_config(page_title="Ruta al WiFi más cercano", layout="centered")
st.title("🌐 Ruta óptima desde tu ubicación hasta el WiFi más cercano")

# Selección
distritos = sorted([
    "Ate", "Barranco", "Breña", "Carabayllo", "Cercado de Lima", "Chorrillos",
    "Comas", "El Agustino", "Independencia", "Jesús María", "La Molina",
    "La Victoria", "Lince", "Los Olivos", "Magdalena del Mar", "Miraflores",
    "Pueblo Libre", "Puente Piedra", "Rímac", "San Borja", "San Isidro",
    "San Juan de Lurigancho", "San Juan de Miraflores", "San Luis",
    "San Martín de Porres", "San Miguel", "Santa Anita", "Santiago de Surco",
    "Surquillo", "Villa El Salvador", "Villa María del Triunfo", "Callao"
])
distrito = st.selectbox("Selecciona un distrito:", distritos)
modo = st.selectbox("Modo de transporte:", ["Peatonal", "Vehicular", "Avión"])
vista = st.radio("Vista de mapa:", ["Clásico", "Satélite"], horizontal=True)

tipo_red = "walk" if modo == "Peatonal" else "drive" if modo == "Vehicular" else None
velocidad_mpm = 75 if modo == "Peatonal" else 250 if modo == "Vehicular" else 833

@st.cache_data
def obtener_wifi(distrito):
    lugar = ox.geocode_to_gdf(f"{distrito}, Lima, Peru")
    tags = {"internet_access": "wlan"}
    gdf = ox.features_from_polygon(lugar.geometry.iloc[0], tags)
    gdf = gdf[gdf.geometry.geom_type == "Point"]
    return pd.DataFrame({
        "nombre_lugar": gdf.get("name", "WiFi público"),
        "latitud": gdf.geometry.y,
        "longitud": gdf.geometry.x
    }).drop_duplicates(subset=["latitud", "longitud"]).reset_index(drop=True)

@st.cache_data
def obtener_grafo(distrito, tipo_red):
    if tipo_red is None: return None
    centro = ox.geocode(f"{distrito}, Lima, Peru")
    grafo = ox.graph_from_point(centro, dist=2000, network_type=tipo_red)
    if grafo.number_of_nodes() == 0: return None
    componente = nx.node_connected_component(grafo.to_undirected(), list(grafo.nodes())[0])
    return grafo.subgraph(componente).copy()

def conectar_con_prim(df, mapa):
    puntos = df[["latitud", "longitud"]].values
    if len(puntos) < 2: return
    visitados = [False] * len(puntos)
    conexiones = []
    visitados[0] = True
    while len(conexiones) < len(puntos) - 1:
        min_dist = float("inf")
        u = v = -1
        for i, (xi, yi) in enumerate(puntos):
            if visitados[i]:
                for j, (xj, yj) in enumerate(puntos):
                    if not visitados[j]:
                        dist = geodesic((xi, yi), (xj, yj)).meters
                        if dist < min_dist:
                            min_dist, u, v = dist, i, j
        if v == -1: break
        visitados[v] = True
        conexiones.append((puntos[u], puntos[v]))
    for a, b in conexiones:
        folium.PolyLine([(a[0], a[1]), (b[0], b[1])], color="blue", weight=2, tooltip="Conexión WiFi (Prim)").add_to(mapa)

# Obtener datos
df = obtener_wifi(distrito)
grafo = obtener_grafo(distrito, tipo_red)
if df.empty:
    st.warning("No se encontraron puntos WiFi.")
    st.stop()

tiles = "OpenStreetMap" if vista == "Clásico" else "Esri.WorldImagery"
m = folium.Map(location=[df.latitud.mean(), df.longitud.mean()], zoom_start=15, tiles=tiles)
for _, row in df.iterrows():
    folium.Marker([row.latitud, row.longitud], popup=row.nombre_lugar or "WiFi público",
                  icon=folium.Icon(color="green")).add_to(m)

conectar_con_prim(df, m)

st.markdown("### 🧭 Haz clic en el mapa para marcar tu ubicación")
respuesta = st_folium(m, width=800, height=600)

if respuesta and respuesta.get("last_clicked"):
    lat_user, lon_user = respuesta["last_clicked"]["lat"], respuesta["last_clicked"]["lng"]
    st.success(f"📍 Ubicación registrada: ({lat_user:.6f}, {lon_user:.6f})")
    punto_usuario = (lat_user, lon_user)
    df["distancia"] = df.apply(lambda row: geodesic(punto_usuario, (row["latitud"], row["longitud"])).meters, axis=1)
    wifi = df.loc[df["distancia"].idxmin()]
    lat_wifi, lon_wifi = wifi["latitud"], wifi["longitud"]
    nombre_wifi = wifi["nombre_lugar"] or "WiFi público"
    distancia = wifi["distancia"]
    tiempo = distancia / velocidad_mpm / 60

    folium.Marker([lat_user, lon_user],
                  tooltip="Tu ubicación",
                  icon=folium.Icon(color="red", icon="user")).add_to(m)

    if modo == "Avión":
        st.markdown(f"📶 WiFi más cercano (línea recta): **{nombre_wifi}**")
        st.markdown(f"📏 Distancia: **{distancia:.1f} m**")
        st.markdown(f"⏱️ Tiempo estimado: **{tiempo:.1f} min**")
        folium.PolyLine([(lat_user, lon_user), (lat_wifi, lon_wifi)],
                        color="purple", weight=4, dash_array="5,5",
                        tooltip="Ruta directa (modo avión)").add_to(m)
        st_folium(m, width=800, height=600)
        st.stop()

    if grafo is None:
        st.error("No se pudo cargar la red vial.")
        st.stop()

    try:
        nodo_origen = ox.distance.nearest_nodes(grafo, lon_user, lat_user)
    except:
        st.error("No se encontró nodo cercano a tu ubicación.")
        st.stop()

    mejor_ruta = None
    menor_dist = float("inf")
    for _, row in df.iterrows():
        try:
            nodo_wifi = ox.distance.nearest_nodes(grafo, row["longitud"], row["latitud"])
            if nx.has_path(grafo, nodo_origen, nodo_wifi):
                ruta = ox.shortest_path(grafo, nodo_origen, nodo_wifi, weight="length")
                dist = sum(grafo.edges[u, v, 0].get("length", 0) for u, v in zip(ruta[:-1], ruta[1:]))
                if dist < menor_dist:
                    mejor_ruta = ruta
                    menor_dist = dist
                    lat_wifi = row["latitud"]
                    lon_wifi = row["longitud"]
                    nombre_wifi = row["nombre_lugar"] or "WiFi público"
        except:
            continue

    if mejor_ruta:
        coords = [(grafo.nodes[n]['y'], grafo.nodes[n]['x']) for n in mejor_ruta]
        st.markdown(f"📶 WiFi más accesible ({modo.lower()}): **{nombre_wifi}**")
        folium.PolyLine([(lat_user, lon_user), coords[0]], color="gray", weight=2).add_to(m)
        folium.PolyLine([coords[-1], (lat_wifi, lon_wifi)], color="gray", weight=2).add_to(m)
        folium.PolyLine(coords, color="orange", weight=6, opacity=0.9,
                        tooltip="Ruta sugerida", dash_array="10,5").add_to(m)
        PolyLineTextPath(
            folium.PolyLine(coords),
            '→', repeat=True, offset=7,
            attributes={'fill': 'orange', 'font-weight': 'bold', 'font-size': '16'}
        ).add_to(m)
        minutos = menor_dist / velocidad_mpm / 60
        st.markdown(f"📏 Distancia: **{menor_dist:.1f} m**")
        st.markdown(f"⏱️ Tiempo estimado: **{minutos:.1f} min**")
        st_folium(m, width=800, height=600)
    else:
        st.error("No se encontró una ruta accesible al punto WiFi.")
