# Thin wrapper around scripts/lab.sh (macOS/Linux/WSL). Windows PowerShell: use scripts\lab.ps1.
LAB := ./scripts/lab.sh
.PHONY: help bootstrap up down nuke status load load-bg load-stop scenario scenario-long analyze synthetic notebook exporter test test-short \
        fault-latency fault-cpu fault-errors fault-reset
DUR ?= 10m
RPS ?= 20

help:          ; @$(LAB) help
bootstrap:     ; ./scripts/bootstrap.sh
up:            ; @$(LAB) up
down:          ; @$(LAB) down
nuke:          ; @$(LAB) nuke
status:        ; @$(LAB) status
load:          ; @$(LAB) load $(DUR) $(RPS)
load-bg:       ; @$(LAB) load-bg $(DUR) $(RPS)
load-stop:     ; @$(LAB) load-stop
scenario:      ; @$(LAB) scenario
scenario-long: ; @$(LAB) scenario --profile long
analyze:       ; @$(LAB) analyze
synthetic:     ; @$(LAB) synthetic
notebook:      ; @$(LAB) notebook
exporter:      ; @$(LAB) exporter
test:          ; @$(LAB) test
test-short:    ; @$(LAB) test-short
fault-latency: ; @$(LAB) fault latency 300
fault-cpu:     ; @$(LAB) fault cpu on
fault-errors:  ; @$(LAB) fault errors 0.2
fault-reset:   ; @$(LAB) fault reset
