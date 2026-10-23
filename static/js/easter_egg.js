/*
 * Easter egg: se a pessoa ficar sem interagir com a página por 10s,
 * mostra uma imagem pequena no canto da tela — some sozinha assim que
 * ela mexe o mouse, digita ou rola de novo.
 */
document.addEventListener("DOMContentLoaded", () => {
  const TEMPO_AUSENCIA = 10000;

  const img = document.createElement("img");
  img.src = "/static/img/easter_egg_violao.gif";
  img.alt = "";
  img.id = "easter-egg-ausencia";
  img.setAttribute("aria-hidden", "true");
  document.body.appendChild(img);

  let temporizador;

  const esconder = () => img.classList.remove("visivel");
  const mostrar = () => img.classList.add("visivel");
  const reiniciarContagem = () => {
    esconder();
    clearTimeout(temporizador);
    temporizador = setTimeout(mostrar, TEMPO_AUSENCIA);
  };

  ["mousemove", "mousedown", "keydown", "scroll", "touchstart", "wheel"].forEach((evento) => {
    document.addEventListener(evento, reiniciarContagem, { passive: true });
  });

  reiniciarContagem();
});
