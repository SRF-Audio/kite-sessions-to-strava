FROM fedora:latest

RUN dnf -y upgrade && \
    dnf -y install \
    python3 python3-pip python3-wheel \
    git ansible gawk \
    && dnf clean all

COPY . /home/dev/workspace
RUN pip3 install --no-cache-dir -r /home/dev/workspace/requirements.txt

WORKDIR /home/dev/workspace

CMD ["python3", "main.py"]
