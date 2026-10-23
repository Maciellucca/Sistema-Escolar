/*
 * Autocompletar dos campos de busca: qualquer <input data-sugestoes="fonte">
 * mostra, enquanto o operador digita, uma listinha com os nomes compatíveis
 * (vindos de /api/sugestoes/<fonte>). Clicar num nome (ou escolher com as
 * setas + Enter) preenche o campo e já envia o formulário de busca.
 *
 * A lista é posicionada em relação à página (e não dentro do formulário),
 * pra não mexer no layout de nenhuma tela que use o campo.
 */
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("input[data-sugestoes]").forEach((campo) => {
    const fonte = campo.dataset.sugestoes;
    campo.setAttribute("autocomplete", "off");

    const lista = document.createElement("div");
    lista.className = "resultados-busca-trocar sugestoes-flutuantes";
    lista.setAttribute("role", "listbox");
    lista.hidden = true;
    document.body.appendChild(lista);

    let itens = [];
    let destacado = -1;
    let temporizador;
    let ultimaConsulta = 0;

    const posicionar = () => {
      const r = campo.getBoundingClientRect();
      lista.style.top = `${r.bottom + window.scrollY}px`;
      lista.style.left = `${r.left + window.scrollX}px`;
      lista.style.width = `${Math.max(r.width, 240)}px`;
    };
    const fechar = () => {
      lista.hidden = true;
      destacado = -1;
    };
    const destacar = (i) => {
      destacado = i;
      itens.forEach((el, j) => el.classList.toggle("destacado", j === i));
      if (itens[i]) itens[i].scrollIntoView({ block: "nearest" });
    };
    const escolher = (valor) => {
      campo.value = valor;
      fechar();
      const form = campo.form;
      if (form) {
        if (form.requestSubmit) form.requestSubmit();
        else form.submit();
      }
    };

    const mostrar = (valores, termo) => {
      lista.innerHTML = "";
      itens = [];
      destacado = -1;
      if (!valores.length) {
        const vazio = document.createElement("div");
        vazio.className = "resultado-busca-trocar muted";
        vazio.textContent = "Nenhum nome encontrado.";
        lista.appendChild(vazio);
      }
      const termoMin = termo.toLowerCase();
      valores.forEach((valor) => {
        const item = document.createElement("div");
        item.className = "resultado-busca-trocar";
        item.setAttribute("role", "option");
        // destaca o trecho digitado dentro do nome
        const pos = valor.toLowerCase().indexOf(termoMin);
        if (pos >= 0) {
          item.append(valor.slice(0, pos));
          const marca = document.createElement("strong");
          marca.textContent = valor.slice(pos, pos + termo.length);
          item.append(marca, valor.slice(pos + termo.length));
        } else {
          item.textContent = valor;
        }
        // mousedown (e não click) pra escolher antes do blur do campo fechar a lista
        item.addEventListener("mousedown", (ev) => {
          ev.preventDefault();
          escolher(valor);
        });
        lista.appendChild(item);
        itens.push(item);
      });
      posicionar();
      lista.hidden = false;
    };

    campo.addEventListener("input", () => {
      clearTimeout(temporizador);
      const termo = campo.value.trim();
      if (!termo) {
        fechar();
        return;
      }
      temporizador = setTimeout(async () => {
        const consulta = ++ultimaConsulta;
        try {
          const resp = await fetch(`/api/sugestoes/${encodeURIComponent(fonte)}?q=${encodeURIComponent(termo)}`);
          if (!resp.ok) return;
          const valores = await resp.json();
          // descarta resposta atrasada de um termo que já foi alterado
          if (consulta !== ultimaConsulta || document.activeElement !== campo) return;
          mostrar(valores, termo);
        } catch (err) {
          fechar();
        }
      }, 150);
    });

    campo.addEventListener("keydown", (ev) => {
      if (lista.hidden || !itens.length) {
        if (ev.key === "Escape") fechar();
        return;
      }
      if (ev.key === "ArrowDown") {
        ev.preventDefault();
        destacar((destacado + 1) % itens.length);
      } else if (ev.key === "ArrowUp") {
        ev.preventDefault();
        destacar(destacado <= 0 ? itens.length - 1 : destacado - 1);
      } else if (ev.key === "Enter" && destacado >= 0) {
        ev.preventDefault();
        escolher(itens[destacado].textContent);
      } else if (ev.key === "Escape") {
        fechar();
      }
    });

    campo.addEventListener("blur", fechar);
    window.addEventListener("resize", () => {
      if (!lista.hidden) posicionar();
    });
  });
});
