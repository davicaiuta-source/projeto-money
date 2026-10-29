# Leitor de Cupom Fiscal (NFC-e)

Web app para celular que lê o QR Code do cupom fiscal eletrônico (NFC-e) e lista os produtos com quantidade, preço unitário e total.

## Como rodar

Precisa só de Python 3 (sem instalar pacotes).

```
python server.py
```

ou dê dois cliques em `iniciar.bat`. O terminal mostra o endereço para abrir no celular (ex.: `http://192.168.0.10:8000`). O celular precisa estar no mesmo Wi-Fi. Na primeira execução, o Windows pode pedir para liberar o Python no firewall: permita em **redes privadas**.

## Câmera ao vivo x foto

- **Ler de uma foto**: funciona sempre. Abre a câmera do celular, você tira a foto do QR e o app lê.
- **Câmera ao vivo**: o navegador só libera em **HTTPS**. Para ter HTTPS sem configurar nada, use um túnel:

  ```
  cloudflared tunnel --url http://localhost:8000
  ```

  Ele gera um link `https://….trycloudflare.com` que funciona no celular, inclusive fora de casa.

No Chrome/Safari do celular, use "Adicionar à tela inicial" para abrir como um app.

## Transformar em link

### Link fixo (grátis, funciona com o PC desligado)

1. Crie uma conta em https://github.com e um repositório novo (ex.: `leitor-cupom`).
2. Na página do repositório, clique em **"uploading an existing file"** e arraste `server.py`, `render.yaml`, `README.md` e a pasta `static` inteira. Clique em **Commit changes**.
3. Crie uma conta em https://render.com (pode entrar com o GitHub).
4. Clique em **New → Blueprint**, escolha o repositório e confirme. O Render lê o `render.yaml` sozinho.
5. Em uns 2 minutos, ele mostra o link, tipo `https://leitor-cupom.onrender.com`. Já é HTTPS, então a câmera ao vivo funciona.

No plano grátis, o servidor "dorme" depois de 15 minutos sem uso. O primeiro acesso depois disso demora uns 30 segundos.

### Link temporário (usa o seu PC)

1. Instale o cloudflared uma vez: `winget install --id Cloudflare.cloudflared`
2. Dê dois cliques em `link-temporario.bat` e use o link `https://….trycloudflare.com` que aparecer.

O link só funciona enquanto essa janela estiver aberta e muda a cada vez que você roda.

## Como funciona

O QR Code da NFC-e é um link para o portal da SEFAZ do estado. O navegador não pode ler essa página direto (bloqueio de CORS), então o `server.py` busca a página e extrai os produtos (`/api/nfce?url=…`). Ele só aceita links de domínios `.gov.br`.

O histórico de cupons lidos fica salvo no próprio celular (localStorage).

## Limitações

- O leitor entende o layout padrão da consulta pública (usado pela maioria dos estados, como SP e PR) e o layout de MG. Ainda não foi testado com cupons reais de cada estado. Se o portal de algum estado usar outro formato ou pedir captcha, o app mostra um botão para abrir o cupom no site da SEFAZ.
- Um cupom recém-emitido pode levar alguns minutos para aparecer na SEFAZ.
