/** @type {import('next').NextConfig} */
export default {
  // El worker vive en otra máquina (contenedor). Nada que reescribir aquí:
  // todo pasa por route handlers para que el token no salga del servidor.
  poweredByHeader: false,
};
