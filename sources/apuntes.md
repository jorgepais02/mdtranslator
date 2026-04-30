# Análisis forense de tráfico de red (IV)

## Recuperación de objetos HTTP

Para una prueba, se creó una página HTML sencilla con un párrafo y una imagen, servida mediante `sudo python3 -m http.server 80` en localhost. Inicialmente, no se capturaba tráfico porque Wireshark escuchaba en la interfaz NS33. Al cambiar a la interfaz EMI (loopback), el tráfico HTTP se hizo visible en texto plano.

Para recuperar la imagen del tráfico, se utiliza la función "Exportar objetos HTTP", donde se puede guardar el archivo `kitten.jpg` directamente. Esta técnica es aplicable a cualquier página o aplicación que utilice HTTP en plano. Aunque menos común en la web actual, sigue siendo relevante para muchas aplicaciones móviles que, por supuesta eficiencia, no cifran tráfico considerado no privado o irrelevante, permitiendo la extracción de imágenes o código HTML.

## Análisis de flujos (Streams)

Para visualizar la comunicación completa de un flujo, se puede hacer clic derecho sobre un paquete y seleccionar "Follow TCP Stream" (o "Follow HTTP Stream"). Wireshark mostrará la petición inicial (GET), todas las cabeceras HTTP de petición y respuesta, y el contenido final (HTML), diferenciando visualmente la petición y la respuesta con colores distintos. Esta funcionalidad también está disponible para otros protocolos, como DNS, utilizando "Follow UDP Stream" para ver consultas a dominios en plano.

## Filtros de visualización avanzados

Wireshark proporciona filtros de visualización potentes para una inspección específica. A diferencia de los BPF (Berkeley Packet Filters), estos filtros no descartan paquetes de la captura, sino que solo ocultan aquellos que no cumplen el criterio en la interfaz de visualización. Es posible filtrar por cualquier campo que Wireshark pueda diseccionar.

- Filtros simples: Se introduce el nombre del protocolo, como `dns`, `http` o `arp`.

- Operadores lógicos y de contenido:
    - `http.referer == "http://localhost/"`: Para identificar la página de origen que llevó a otra.
    - `http.user_agent contains "Mozilla"`: Para determinar el explorador y sistema operativo del usuario (ej., Firefox en Linux).
    - `http.request.full_uri contains "kit"`: Para localizar una petición específica, como la de la imagen del gatito.

## Filtrado de protocolos (Caso DNS)

Para visualizar únicamente las respuestas DNS, se puede aplicar el filtro `dns.flags.response == 1` en la disección de protocolos. Si se establece el valor en `0`, se mostrarán las consultas (queries).

Para una búsqueda más específica, como determinar la dirección IP exacta a la que se tradujo un dominio como `google.com`, se puede combinar la respuesta con el contenido del paquete utilizando el filtro `dns.flags.response == 1 and frame contains "google"`. En un ejemplo práctico, una consulta a Google se tradujo a la dirección IP `142.250.201.68`.
