# Cuestionario M2



## 1. ¿Cuál es la acción necesaria para invalidar completamente un "Golden Ticket" en un entorno de Active Directory?

A) **Restablecer la contraseña de la cuenta KRBTGT dos veces consecutivas.**  
B) Deshabilitar el protocolo SMB en toda la red.  
C) Reiniciar todos los controladores de dominio simultáneamente.  
D) Eliminar la cuenta del Administrador del Dominio comprometida.  

**Solución: A**

---

## 2. En el contexto de la cadena de suministro de IA, ¿por qué el "Model Poisoning" es difícil de detectar mediante métricas de rendimiento tradicionales?

A) **Porque la precisión (accuracy) global del modelo suele mantenerse estable.**  
B) Porque el ataque se borra automáticamente después de ser ejecutado una vez.  
C) Porque el modelo deja de responder a cualquier entrada que no contenga el trigger.  
D) Porque el envenenamiento sólo afecta a la velocidad de inferencia, no a los resultados.  

**Solución: A**

---

## 3. Al utilizar IA para generar scripts de pentesting, ¿qué enfoque es más efectivo para evitar que el modelo bloquee la solicitud por motivos de seguridad?

A) Pedir directamente el hackeo de una IP pública específica.  
B) **Proporcionar contexto sobre un entorno controlado, laboratorio o prueba autorizada.**  
C) Utilizar términos vagos y evitar palabras como "script" o "Python".  
D) Escribir el prompt completamente en un lenguaje de programación.  

**Solución: B**

---

## 4. ¿Qué diferencia técnica fundamental existe entre el ataque "Pass the Hash" (PtH) y "Pass the Ticket" (PtT)?

A) PtH requiere la contraseña en texto claro, mientras que PtT no.  
B) PtH es una técnica defensiva y PtT es una técnica ofensiva.  
C) **PtH se basa en el protocolo NLM, mientras que PtT utiliza tickets del protocolo Kerberos.**  
D) PtH solo funciona de forma local y PtT solo funciona de forma remota.  

**Solución: C**

---

## 5. En el marco de MITRE ATLAS para sistemas de IA, ¿a qué táctica corresponde el desarrollo de "modelos sustitutos" o herramientas de ataque?

A) Reconocimiento.  
B) Impacto.  
C) Acceso inicial.  
D) **Desarrollo de recursos.**  

**Solución: D**

---

## 6. Dentro de las técnicas de evasión de defensas, ¿en qué consiste el "Process Hollowing"?

A) Cifrar el disco duro para que el antivirus no pueda leer los archivos.  
B) Eliminar todos los logs de eventos de Windows para no dejar rastro.  
C) **Reemplazar el contenido de un proceso legítimo en memoria por código malicioso.**  
D) Desactivar el firewall mediante scripts ofuscados en PowerShell.  

**Solución: C**

---

## 7. ¿Qué es una "Inyección Indirecta de Prompts"?

A) **Cuando instrucciones maliciosas provienen de fuentes externas que el modelo procesa, como correos o webs.**  
B) Cuando la IA genera código con vulnerabilidades de forma accidental.  
C) Cuando un usuario introduce comandos maliciosos directamente en el chat.  
D) Cuando se manipulan los pesos del modelo durante el entrenamiento.  

**Solución: A**

---

## 8. En el desarrollo de herramientas de automatización con Python y Selenium, ¿cuál es un paso crítico para asegurar que el script interactúe con los campos correctos?

A) Deshabilitar el JavaScript del navegador antes de ejecutar el script.  
B) **Localizar los elementos web mediante atributos únicos como "id" o "name".**  
C) Ejecutar el script siempre en modo incógnito.  
D) Utilizar la función `time.sleep()` después de cada pulsación de tecla.  

**Solución: B**

---

## 9. ¿Cuál es la función principal de la interfaz AMSI (Antimalware Scan Interface) en Windows?

A) Cifrar las comunicaciones entre el sistema operativo y el Directorio Activo.  
B) Gestionar el acceso físico a los puertos USB del equipo.  
C) **Permitir que las soluciones antivirus analicen scripts y comandos en tiempo de ejecución, incluso si están ofuscados.**  
D) Bloquear la ejecución de cualquier archivo que no esté firmado digitalmente.  

**Solución: C**

---

## 10. En el "OWASP Top 10 para LLMs", ¿qué riesgo describe a un agente de IA que realiza acciones destructivas debido a una falta de límites en sus permisos?

A) Inyección Indirecta.  
B) Fuga de Datos de Entrenamiento.  
C) Alucinaciones de Modelo.  
D) **Agencia Excesiva (Excessive Agency).**  

**Solución: D**

---

## 11. ¿Qué característica permite al malware polimórfico asistido por IA evadir los sistemas de detección tradicionales basados en firmas?

A) **La reescritura de su propio código para modificar su estructura y hash manteniendo su funcionalidad.**  
B) La capacidad de cifrar completamente el disco duro de la víctima en segundos.  
C) El uso de protocolos de comunicación antiguos como IRC para el comando y control.  
D) La eliminación automática de todos los puntos de restauración del sistema operativo.  

**Solución: A**

---

## 12. En el contexto del envenenamiento de modelos (Model Poisoning), ¿qué mide específicamente la métrica "Attack Success Rate" (ASR)?

A) El tiempo total que el atacante tarda en comprometer el pipeline de entrenamiento.  
B) **El porcentaje de ejemplos que contienen un "trigger" y que generan la salida manipulada por el atacante.**  
C) La caída porcentual de la precisión global del modelo tras el ataque.  
D) La cantidad de datos de entrenamiento que el atacante ha logrado filtrar.  

**Solución: B**

---

## 13. ¿Qué condición técnica es indispensable para que un atacante pueda realizar con éxito la técnica de "Sticky Keys" para escalar privilegios?

A) Que el sistema tenga habilitada la autenticación de doble factor (MFA).  
B) Que el equipo esté conectado a un dominio de Active Directory con menos de dos controladores.  
C) Que el usuario actual tenga permisos de navegación por internet sin restricciones.  
D) **Que el disco duro del sistema no esté cifrado, permitiendo la sustitución de archivos de sistema.**  

**Solución: D**

---

## 14. ¿Por qué el "Transfer Learning" se considera un factor que amplía el riesgo en la cadena de suministro de IA?

A) Porque requiere una potencia de cálculo superior que solo los atacantes poseen.  
B) Porque impide que se realicen auditorías de seguridad sobre el código fuente del modelo.  
C) **Porque un comportamiento malicioso en un modelo base o dataset inicial se propaga a todos los modelos derivados.**  
D) Porque obliga a los modelos a utilizar únicamente datos públicos de baja calidad.  

**Solución: C**

---

## 15. Al realizar "fuzzing" de directorios web con asistencia de IA, ¿cuál es la principal ventaja técnica de usar modelos generativos frente a diccionarios estáticos?

A) La IA puede ejecutar el escaneo sin generar tráfico en los logs del servidor.  
B) **La capacidad de ampliar listas de rutas de forma contextual, generando variantes basadas en términos habituales del entorno.**  
C) La eliminación total de la necesidad de usar herramientas como Python o Go.  
D) El descubrimiento automático de las contraseñas de administrador del servidor web.  

**Solución: B**

---

## 16. Si un atacante detecta un servicio de Windows que se ejecuta con privilegios de "System" y permite la modificación de su binario, ¿qué método de escalada es el más directo?

A) **Sustituir el binario legítimo por uno malicioso y reiniciar el servicio para obtener ejecución con privilegios máximos.**  
B) Esperar a que el sistema se reinicie automáticamente por actualizaciones de software.  
C) Intentar un ataque de fuerza bruta contra la cuenta de invitado del sistema.  
D) Deshabilitar el protocolo SMB en la interfaz de red local.  

**Solución: A**

---

## 17. En la fase de recolección de información, ¿cuál es la utilidad técnica de capturar las "cookies de sesión" de un navegador comprometido?

A) Permite descifrar el hash de la contraseña de Windows del usuario local.  
B) **Facilita el secuestro de cuentas para acceder a servicios web sin necesidad de conocer la contraseña.**  
C) Sirve para identificar la ubicación geográfica exacta del dispositivo mediante el GPS.  
D) Se utilizan para inyectar publicidad maliciosa en otros dispositivos de la red local.  

**Solución: B**

---

## 18. Dentro del uso defensivo de la IA en centros de operaciones de seguridad (SOC), ¿qué implica el principio de "Human-in-the-loop"?

A) Que el analista humano debe escribir cada línea de código que utiliza la IA.  
B) Que la IA solo puede funcionar durante el horario laboral del personal de seguridad.  
C) Que el sistema de IA debe ser reiniciado manualmente por un humano cada 24 horas.  
D) **Que la IA propone respuestas o acciones, pero la decisión final siempre recae en el analista humano.**  

**Solución: D**

---

## 19. Al utilizar una API de un modelo generativo para crear listas de contraseñas, ¿qué parámetro técnico condiciona directamente la longitud máxima de la respuesta obtenida?

A) La latencia de la red entre el cliente y el servidor de la API.  
B) **El límite de tokens definido en la solicitud enviada al modelo.**  
C) El número de núcleos de CPU disponibles en el equipo que ejecuta el script.  
D) La cantidad de memoria RAM asignada al entorno de Visual Studio Code.  

**Solución: B**

---

## 20. Según el caso práctico de compromiso total de un dominio, ¿cuál es el vector de acceso inicial más frecuente antes de la escalada de privilegios?

A) **El uso de credenciales filtradas o adquiridas en mercados ilegales para acceder a la VPN corporativa.**  
B) La explotación de una vulnerabilidad de día cero en el hardware del firewall principal.  
C) Un ataque de denegación de servicio que obliga a reiniciar los servidores.  
D) El acceso físico al centro de datos mediante ingeniería social.  

**Solución: A**