#!/bin/bash
# simulate (faster!) serial input by dumping an existing dump line by line into the buffer file
while read p; do
  echo "$p" >> /tmp/scope.dump
  sleep 0.3
done < ../../../Traces/scope.dump
