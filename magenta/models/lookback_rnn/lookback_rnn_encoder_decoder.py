# Copyright 2016 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""A MelodyEncoderDecoder specific to the lookback RNN model."""

# internal imports
from magenta.music import melodies_lib

NUM_SPECIAL_EVENTS = melodies_lib.NUM_SPECIAL_EVENTS
NO_EVENT = melodies_lib.NO_EVENT
STEPS_PER_BAR = 16  # This code assumes the melodies have 16 steps per bar.

MIN_NOTE = 48  # Inclusive
MAX_NOTE = 84  # Exclusive
TRANSPOSE_TO_KEY = 0  # C Major

# Must be sorted in ascending order.
LOOKBACK_DISTANCES = [STEPS_PER_BAR, STEPS_PER_BAR * 2]

# The number of special input indices and label values other than the events
# in the note range.
NUM_SPECIAL_INPUTS = 7
NUM_SPECIAL_LABELS = len(LOOKBACK_DISTANCES)
NUM_BINARY_TIME_COUNTERS = 5


class MelodyEncoderDecoder(melodies_lib.MelodyEncoderDecoder):
  """A MelodyEncoderDecoder specific to the lookback RNN model.

  Attributes:
    num_model_events: The number of different melody events that can be
        generated by this model.
  """

  def __init__(self):
    """Initializes the MelodyEncoderDecoder."""
    super(MelodyEncoderDecoder, self).__init__(MIN_NOTE, MAX_NOTE,
                                               TRANSPOSE_TO_KEY)
    self.num_model_events = self.max_note - self.min_note + NUM_SPECIAL_EVENTS

  @property
  def input_size(self):
    return 3 * self.num_model_events + NUM_SPECIAL_INPUTS

  @property
  def num_classes(self):
    return self.num_model_events + NUM_SPECIAL_LABELS

  def melody_event_to_model_event(self, melody_event):
    """Collapses a melody event value into a zero-based index range.

    Args:
      melody_event: A MonophonicMelody event value. -2 = no event,
          -1 = note-off event, [0, 127] = note-on event for that midi pitch.

    Returns:
      An int in the range [0, self._num_model_events). 0 = no event,
      1 = note-off event, [2, self._num_model_events) = note-on event for
      that pitch relative to the [self._min_note, self._max_note) range.
    """
    if melody_event < 0:
      return melody_event + NUM_SPECIAL_EVENTS
    return melody_event - self.min_note + NUM_SPECIAL_EVENTS

  def model_event_to_melody_event(self, model_event):
    """Expands a zero-based index value to its equivalent melody event value.

    Args:
      model_event: An int in the range [0, self._num_model_events).
          0 = no event, 1 = note-off event,
          [2, self._num_model_events) = note-on event for that pitch relative
          to the [self._min_note, self._max_note) range.

    Returns:
      A MonophonicMelody event value. -2 = no event, -1 = note-off event,
      [0, 127] = note-on event for that midi pitch.
    """
    if model_event < NUM_SPECIAL_EVENTS:
      return model_event - NUM_SPECIAL_EVENTS
    return model_event - NUM_SPECIAL_EVENTS + self.min_note

  def events_to_input(self, events, position):
    """Returns the input vector for the given position in the melody.

    Returns a self.input_size length list of floats. Assuming MIN_NOTE = 48
    and MAX_NOTE = 84, self.input_size will = 121. Each index represents a
    different input signal to the model.

    Indices [0, 121):
    [0, 38): Event of current step.
    [38, 76): Event of next step if repeating 1 bar ago.
    [76, 114): Event of next step if repeating 2 bars ago.
    114: 16th note binary counter.
    115: 8th note binary counter.
    116: 4th note binary counter.
    117: Half note binary counter.
    118: Whole note binary counter.
    119: The current step is repeating 1 bar ago.
    120: The current step is repeating 2 bars ago.

    Args:
      events: A melodies_lib.MonophonicMelody object.
      position: An integer position in the melody.

    Returns:
      An input vector, an self.input_size length list of floats.
    """
    input_ = [0.0] * self.input_size

    # Last event.
    model_event = self.melody_event_to_model_event(events[position])
    input_[model_event] = 1.0

    # Next event if repeating N positions ago.
    for i, lookback_distance in enumerate(LOOKBACK_DISTANCES):
      lookback_position = position - lookback_distance + 1
      if lookback_position < 0:
        melody_event = NO_EVENT
      else:
        melody_event = events[lookback_position]
      model_event = self.melody_event_to_model_event(melody_event)
      input_[i * self.num_model_events + model_event] = 1.0

    # Binary time counter giving the metric location of the *next* note.
    n = position + 1
    for i in range(NUM_BINARY_TIME_COUNTERS):
      input_[3 * self.num_model_events + i] = 1.0 if (n / 2 ** i) % 2 else -1.0

    # Last event is repeating N bars ago.
    for i, lookback_distance in enumerate(LOOKBACK_DISTANCES):
      lookback_position = position - lookback_distance
      if (lookback_position >= 0 and
          events[position] == events[lookback_position]):
        input_[3 * self.num_model_events + 5 + i] = 1.0

    return input_

  def events_to_label(self, events, position):
    """Returns the label for the given position in the melody.

    Returns an integer in the range [0, self.num_classes). Indices in the range
    [0, self.num_model_events) map to standard midi events. Indices
    self.num_model_events and self.num_model_events + 1 are signals to repeat
    events from earlier in the melody. More distant repeats are selected first
    and standard midi events are selected last.

    Assuming MIN_NOTE = 48 and MAX_NOTE = 84, then self.num_classes = 40,
    self.num_model_events = 38, and the values will be as follows.
    Values [0, 40):
      [0, 38): Event of the last step in the melody, if not repeating 1 or 2
               bars ago.
      38: If the last event in the melody is repeating 1 bar ago, if not
          repeating 2 bars ago.
      39: If the last event in the melody is repeating 2 bars ago.

    Args:
      events: A melodies_lib.MonophonicMelody object.
      position: An integer position in the melody.

    Returns:
      A label, an integer.
    """
    if (position < LOOKBACK_DISTANCES[-1] and
        events[position] == NO_EVENT):
      return self.num_model_events + len(LOOKBACK_DISTANCES) - 1

    # If last step repeated N bars ago.
    for i, lookback_distance in reversed(list(enumerate(LOOKBACK_DISTANCES))):
      lookback_position = position - lookback_distance
      if (lookback_position >= 0 and
          events[position] == events[lookback_position]):
        return self.num_model_events + i

    # If last step didn't repeat at one of the lookback positions, use the
    # specific event.
    return self.melody_event_to_model_event(events[position])

  def class_index_to_event(self, class_index, events):
    """Returns the melody event for the given class index.

    This is the reverse process of the self.melody_to_label method.

    Args:
      class_index: An int in the range [0, self.num_classes).
      events: The melodies_lib.MonophonicMelody events list of the current
          melody.

    Returns:
      A melodies_lib.MonophonicMelody event value.
    """
    # Repeat N bar ago.
    for i, lookback_distance in reversed(list(enumerate(LOOKBACK_DISTANCES))):
      if class_index == self.num_model_events + i:
        if len(events) < lookback_distance:
          return NO_EVENT
        return events[-lookback_distance]

    # Return the melody event for that class index.
    return self.model_event_to_melody_event(class_index)
