# Usa una imagen base de Python
FROM python:3.12

# Establece el directorio de trabajo dentro del contenedor
WORKDIR /app

# Copia los archivos del proyecto
COPY . .

# Instala las dependencias
RUN pip install --no-cache-dir -r requirements.txt

# Ejecuta el script al iniciar el contenedor
CMD ["python", "main.py"]
