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

# Selectores
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
tipo_mapa = st.radio("Vista del mapa:", ["Clásico", "Satélite"], horizontal=True)

tipo_red = "walk" if modo == "Peatonal" else "drive" if modo == "Vehicular" else None
velocidad_mpm = 75 if modo == "Peatonal" else 250 if modo == "Vehicular" else 833  # 50 km/h aprox

@st.cache_data
def obtener_wifi(distrito):
    lugar = ox.geocode_to_gdf(f"{distrito}, Lima, Peru")
    tags = {"internet_access": "wlan"}
    gdf = ox.features_from_polygon(lugar.geometry.iloc[0], tags)
    gdf = gdf[gdf.geometry.geom_type == "Point"]
    df = pd.DataFrame({
        "nombre_lugar": gdf.get("name", "WiFi público"),
        "latitud": gdf.geometry.y,
        "longitud": gdf.geometry.x
    })
    return df.reset_index(drop=True)

@st.cache_data
def obtener_grafo(distrito, tipo_red):
    if tipo_red is None:
        return None
    centro = ox.geocode(f"{distrito}, Lima, Peru")
    grafo = ox.graph_from_point(centro, dist=2000, network_type=tipo_red)
    if grafo.number_of_nodes() == 0:
        return None
    componente = nx.node_connected_component(grafo.to_undirected(), list(grafo.nodes())[0])
    return grafo.subgraph(componente).copy()

def conectar_con_prim(df, mapa):
    lugares = df[["nombre_lugar", "latitud", "longitud"]].values
    if len(lugares) < 2:
        return
    visitados = [False] * len(lugares)
    conexiones = []
    visitados[0] = True
    while len(conexiones) < len(lugares) - 1:
        min_dist = float("inf")
        u = v = -1
        for i in range(len(lugares)):
            if visitados[i]:
                for j in range(len(lugares)):
                    if not visitados[j]:
                        dist = geodesic((lugares[i][1], lugares[i][2]), (lugares[j][1], lugares[j][2])).meters
                        if dist < min_dist:
                            min_dist = dist
                            u, v = i, j
        if v == -1:
            break
        visitados[v] = True
        conexiones.append((lugares[u], lugares[v]))
    for a, b in conexiones:
        folium.PolyLine([(a[1], a[2]), (b[1], b[2])], color="blue", weight=2, tooltip="Conexión WiFi (Prim)").add_to(mapa)

# Cargar datos
df = obtener_wifi(distrito)
grafo = obtener_grafo(distrito, tipo_red)

if df.empty:
    st.warning("No se encontraron puntos WiFi.")
    st.stop()

df.drop_duplicates(subset=["latitud", "longitud"], inplace=True)
tiles_map = "OpenStreetMap" if tipo_mapa == "Clásico" else "Esri.WorldImagery"
m = folium.Map(location=[df.latitud.mean(), df.longitud.mean()], zoom_start=15, tiles=tiles_map)

for _, row in df.iterrows():
    folium.Marker(
        [row.latitud, row.longitud],
        popup=row.nombre_lugar or "WiFi público",
        icon=folium.Icon(color="green")
    ).add_to(m)

conectar_con_prim(df, m)

st.markdown("### 🧭 Haz clic en el mapa para marcar tu ubicación")
respuesta = st_folium(m, width=800, height=600)

if respuesta and respuesta.get("last_clicked"):
    lat_user = respuesta["last_clicked"]["lat"]
    lon_user = respuesta["last_clicked"]["lng"]
    st.success(f"📍 Ubicación registrada: ({lat_user:.6f}, {lon_user:.6f})")

    punto_usuario = (lat_user, lon_user)
    df["distancia"] = df.apply(lambda row: geodesic(punto_usuario, (row["latitud"], row["longitud"])).meters, axis=1)
    wifi_seleccionado = df.loc[df["distancia"].idxmin()]

    lat_wifi = wifi_seleccionado["latitud"]
    lon_wifi = wifi_seleccionado["longitud"]
    nombre_wifi = wifi_seleccionado["nombre_lugar"] or "WiFi público"
    distancia = wifi_seleccionado["distancia"]
    tiempo = distancia / velocidad_mpm / 60

    folium.Marker([lat_user, lon_user],
                  tooltip="Tu ubicación",
                  icon=folium.Icon(color="red", icon="user")).add_to(m)

    if modo == "Avión":
        st.markdown(f"📶 WiFi más cercano (línea recta): **{nombre_wifi}**")
        st.markdown(f"📏 Distancia: **{distancia:.1f} metros**")
        st.markdown(f"⏱️ Tiempo estimado: **{tiempo:.1f} minutos**")

        folium.PolyLine(
            [(lat_user, lon_user), (lat_wifi, lon_wifi)],
            color="purple", weight=4, dash_array="5,5",
            tooltip="Ruta directa (modo avión)"
        ).add_to(m)

        st_folium(m, width=800, height=600)
        st.stop()

    if grafo is None:
        st.error("No se pudo cargar el grafo para este modo.")
        st.stop()

    try:
        nodo_origen = ox.distance.nearest_nodes(grafo, lon_user, lat_user)
    except:
        st.error("No se pudo ubicar tu punto dentro de la red vial.")
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

        folium.PolyLine([(lat_user, lon_user), coords[0]], color="gray", weight=2, tooltip="Conexión al grafo").add_to(m)
        folium.PolyLine([coords[-1], (lat_wifi, lon_wifi)], color="gray", weight=2, tooltip="Tramo final al WiFi").add_to(m)

        folium.PolyLine(
            coords, color="orange", weight=6, opacity=0.9,
            tooltip="Ruta sugerida", dash_array="10,5"
        ).add_to(m)

        PolyLineTextPath(
            folium.PolyLine(coords),
            '→
