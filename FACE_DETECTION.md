# Optional Face Detection Layer

This layer uses OpenCV YuNet to detect faces in each camera frame. It returns a
face box, five landmarks, and detector confidence only. It does not identify,
compare, search for, or name a person.

## What is deployed

`models/face/yunet.onnx` is the official OpenCV Zoo YuNet model, published
under the MIT License. It is mounted read-only into the vision container and is
used with OpenCV's `FaceDetectorYN` runtime already included in the vision
image.

Each face observation receives a short-lived anonymous `face_track_id`. When
the face lies within a confirmed person detection, that ID follows the existing
anonymous ByteTrack person ID; otherwise it uses only recent bounding-box
overlap. It never uses face appearance, embeddings, identity, or a gallery.

The preview draws a purple `FACE <confidence>%` box. If
`PRIVACY_BLUR_FACES=true` (the deployment default), the inside of every face
box is blurred before the preview is encoded. No face crop, embedding, identity
or reference-photo gallery is stored or sent by this system.

## Start the layer

From `C:\Users\ASUS\Downloads\fpv`, run:

```powershell
& "D:\Docker\Desktop\resources\bin\docker.exe" compose `
  -f .\docker-compose.yml `
  -f .\docker-compose.face.yml `
  --profile vision up --build -d vision
```

To turn it off, run the regular vision command without
`docker-compose.face.yml`.
