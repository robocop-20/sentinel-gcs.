# Face Observation Quality Layer

The face observation layer improves operator awareness without identifying a
person. Every detected face can carry these transparent, per-frame signals:

- detector confidence and five landmarks from YuNet;
- anonymous `linked_track_id` when the face centre is inside a current YOLO +
  ByteTrack `person` box;
- quality score from sharpness, lighting, face size, and landmark-based
  frontal-pose heuristics;
- explicit issue codes such as `face_too_small`, `low_sharpness`,
  `poor_lighting`, and `non_frontal_pose`.

`usable_for_operator_review=true` only means the image has passed the configured
visual-quality threshold. It is not an identity result, a match, an alert, or
an authorisation to retain the face image.

No facial vector, embedding, uploaded reference portrait, face crop, identity,
or face-search query is created or stored. The existing `PRIVACY_BLUR_FACES`
setting continues to blur every detected face before the preview is encoded.
