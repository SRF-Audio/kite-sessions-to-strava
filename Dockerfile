FROM fedora:latest

# Ensure the container has all necessary packages
RUN dnf -y upgrade && \
    dnf -y install \
    python3 \
    python3-pip \
    python3-wheel \
    git \
    ansible \
    gawk \
    && dnf clean all

# Install zsh and oh-my-zsh
RUN dnf -y install zsh && \
    sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" --unattended && \
    sed -i 's/^plugins=(.*)/plugins=(git python ansible)/' /root/.zshrc && \
    echo "source /root/.zshrc" >> /root/.bashrc && \
    echo "export TERM=xterm-256color" >> /root/.zshrc

# make zsh the default shell
RUN chsh -s $(which zsh)


# Optional: symlink python3 to python
RUN ln -s /usr/bin/python3 /usr/bin/python || true
RUN git config --global user.name "SRF-Audio" && \
    git config --global user.email "srfaudioproductions@gmail.com"

COPY . /kite-strava
WORKDIR /kite-strava

CMD [ "sleep", "infinity" ]
