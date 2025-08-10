from machine import Pin, PWM
import time, random, sys
import uselect

SPEAKER_PIN = 8
pwm = PWM(Pin(SPEAKER_PIN))
pwm.duty_u16(0)

EFFECT_SLIDE = 0
EFFECT_WARBLE = 1
EFFECT_TONE_SEQ = 2
EFFECT_CUSTOM = 3


class EmotionStrategy:
    def play(self, emotion):
        pass


class SlideEmotionStrategy(EmotionStrategy):
    def play(self, emotion):
        slide_tone(emotion.start_freq, emotion.end_freq, emotion.duration, emotion.steps)


class WarbleEmotionStrategy(EmotionStrategy):
    def play(self, emotion):
        warble_tone(emotion.start_freq, emotion.duration, emotion.extra)


class ToneSeqEmotionStrategy(EmotionStrategy):
    def play(self, emotion):
        for _ in range(max(1, emotion.repeat_count)):
            rng = max(0, emotion.end_freq - emotion.start_freq)
            freq = emotion.start_freq + (random.randint(0, rng) if rng > 0 else 0)
            if emotion.extra:
                freq += random.randint(-emotion.extra, emotion.extra)
            play_tone(freq, emotion.duration)
            time.sleep_ms(40)


class CustomEmotionStrategy(EmotionStrategy):
    def play(self, emotion):
        if emotion.name == "CURIOUS":
            slide_tone(emotion.start_freq, emotion.end_freq, emotion.duration, emotion.steps)
            slide_tone(emotion.end_freq, random.randint(500, 800), 200, 10)
        elif emotion.name == "EXCITED":
            for _ in range(max(1, emotion.repeat_count)):
                slide_tone(emotion.start_freq, emotion.end_freq, emotion.duration, emotion.steps)
        elif emotion.name == "TALK":
            play_chirp()
        elif emotion.name == "PURR" or emotion.name.startswith("PURR_"):
            self._play_purr(emotion)

    def _play_purr(self, emotion):
        # Use emotion parameters in a more advanced way
        base_freq = emotion.start_freq
        max_freq = emotion.end_freq
        duration = emotion.duration
        vibrato_depth = emotion.extra
        pulse_pattern = emotion.steps  # Using steps as pulse pattern

        end_time = time.ticks_add(time.ticks_ms(), duration)

        # Create pulse patterns based on steps parameter
        if pulse_pattern == 0:
            pulse_patterns = [(100, 50)]  # Default pattern
        elif pulse_pattern == 1:
            pulse_patterns = [(80, 40), (60, 30)]
        elif pulse_pattern == 2:
            pulse_patterns = [(50, 25), (70, 35), (90, 45)]
        elif pulse_pattern == 3:
            pulse_patterns = [(40, 20), (60, 30), (80, 40), (60, 30)]
        elif pulse_pattern == 4:
            pulse_patterns = [(30, 15), (50, 25), (70, 35), (90, 45), (70, 35)]
        elif pulse_pattern == 5:
            pulse_patterns = [(20, 10), (40, 20), (60, 30), (80, 40), (100, 50), (80, 40)]
        else:
            # Random pattern for higher values
            pulse_patterns = []
            for _ in range(max(2, pulse_pattern // 2)):
                pulse_patterns.append((random.randint(30, 100), random.randint(15, 50)))

        pattern_index = 0
        pattern_length = len(pulse_patterns)

        # Generate pulse sequence
        while time.ticks_diff(end_time, time.ticks_ms()) > 0:
            high_vol, low_vol = pulse_patterns[pattern_index]
            pattern_index = (pattern_index + 1) % pattern_length

            freq_range = max_freq - base_freq
            if freq_range > 0:
                current_freq = base_freq + random.randint(0, freq_range)
            else:
                current_freq = base_freq

            if vibrato_depth > 0:
                current_freq += random.randint(-vibrato_depth, vibrato_depth)

            high_duration = random.randint(high_vol - 10, high_vol + 10)
            low_duration = random.randint(low_vol - 5, low_vol + 5)

            high_vol_value = int(_VOL * emotion.intensity * (high_vol / 100))
            low_vol_value = int(_VOL * emotion.intensity * 0.3 * (low_vol / 100))

            pwm.freq(int(current_freq))
            pwm.duty_u16(high_vol_value)
            time.sleep_ms(max(1, high_duration))
            pwm.duty_u16(low_vol_value)
            time.sleep_ms(max(1, low_duration))

            # Add random pause for more natural sound (10% chance)
            if random.random() < 0.1:
                pause_duration = random.randint(5, 20)
                pwm.duty_u16(0)
                time.sleep_ms(pause_duration)

        mute()


class Emotion:
    _strategies = {
        EFFECT_SLIDE: SlideEmotionStrategy(),
        EFFECT_WARBLE: WarbleEmotionStrategy(),
        EFFECT_TONE_SEQ: ToneSeqEmotionStrategy(),
        EFFECT_CUSTOM: CustomEmotionStrategy()
    }

    def __init__(self, name, effect_type, start_freq, end_freq, duration, steps, repeat_count, extra, intensity=1.0, priority=0, category=None):
        self.name = name
        self.effect_type = effect_type
        self.start_freq = start_freq
        self.end_freq = end_freq
        self.duration = duration
        self.steps = steps
        self.repeat_count = repeat_count
        self.extra = extra
        self.intensity = intensity
        self.priority = priority
        self.category = category or "default"

    def __str__(self):
        return self.name

    def __repr__(self):
        effect_names = ["SLIDE", "WARBLE", "TONE_SEQ", "CUSTOM"]
        effect_name = effect_names[self.effect_type] if 0 <= self.effect_type < len(effect_names) else str(self.effect_type)
        return f"Emotion({self.name}, {effect_name}, {self.start_freq}Hz-{self.end_freq}Hz, {self.duration}ms, int:{self.intensity:.1f})"

    def info(self):
        """Returns a dictionary with information about the emotion in a readable format"""
        effect_names = ["SLIDE", "WARBLE", "TONE_SEQ", "CUSTOM"]
        effect_name = effect_names[self.effect_type] if 0 <= self.effect_type < len(effect_names) else str(self.effect_type)

        return {
            "name": self.name,
            "effect": effect_name,
            "frequency": f"{self.start_freq}Hz-{self.end_freq}Hz",
            "duration": f"{self.duration}ms",
            "steps": self.steps,
            "repeat": self.repeat_count,
            "extra": self.extra,
            "intensity": f"{self.intensity:.1f}",
            "category": self.category
        }

    def play(self):
        global _VOL
        original_vol = _VOL
        _VOL = int(_VOL * self.intensity)
        try:
            self._strategies[self.effect_type].play(self)
        finally:
            _VOL = original_vol

    def get_duration_ms(self):
        if self.effect_type == EFFECT_TONE_SEQ:
            return self.duration * self.repeat_count + 40 * (self.repeat_count - 1)
        return self.duration

    def is_custom(self):
        return self.effect_type == EFFECT_CUSTOM

    def mix_with(self, other_emotion, weight=0.5, custom_name=None):
        """
        Creates a new emotion by mixing this emotion with another.

        Args:
            other_emotion: Second emotion to mix with
            weight: Weight of the second emotion (0.0 - 1.0)
            custom_name: Custom name for the new emotion (optional)

        Returns:
            A new emotion that is a mix of the two input emotions
        """
        # If effect_type is different, choose dominant based on weight
        if self.effect_type != other_emotion.effect_type:
            effect_type = other_emotion.effect_type if weight > 0.5 else self.effect_type
        else:
            effect_type = self.effect_type

        # Numeric parameters - linear interpolation
        start_freq = self.start_freq * (1 - weight) + other_emotion.start_freq * weight
        end_freq = self.end_freq * (1 - weight) + other_emotion.end_freq * weight
        duration = int(self.duration * (1 - weight) + other_emotion.duration * weight)

        # Integer parameters - weighted average
        steps = int(self.steps * (1 - weight) + other_emotion.steps * weight)
        repeat_count = int(self.repeat_count * (1 - weight) + other_emotion.repeat_count * weight)
        extra = int(self.extra * (1 - weight) + other_emotion.extra * weight)

        # Weighted average for intensity and priority
        intensity = self.intensity * (1 - weight) + other_emotion.intensity * weight
        priority = int(self.priority * (1 - weight) + other_emotion.priority * weight)

        # Name
        if custom_name:
            name = custom_name
        else:
            if weight <= 0.25:
                name = f"{self.name}_with_{other_emotion.name}"
            elif weight >= 0.75:
                name = f"{other_emotion.name}_with_{self.name}"
            else:
                name = f"{self.name}_{other_emotion.name}"

        # Category - choose dominant or "mixed"
        if self.category == other_emotion.category:
            category = self.category
        else:
            if weight <= 0.25:
                category = self.category
            elif weight >= 0.75:
                category = other_emotion.category
            else:
                category = "mixed"

        return Emotion(
            name,
            effect_type,
            start_freq,
            end_freq,
            duration,
            steps,
            repeat_count,
            extra,
            intensity,
            priority,
            category
        )

    def to_dict(self):
        return {
            "name": self.name,
            "effect_type": self.effect_type,
            "start_freq": self.start_freq,
            "end_freq": self.end_freq,
            "duration": self.duration,
            "steps": self.steps,
            "repeat_count": self.repeat_count,
            "extra": self.extra,
            "intensity": self.intensity,
            "priority": self.priority,
            "category": self.category
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            data["name"],
            data["effect_type"],
            data["start_freq"],
            data["end_freq"],
            data["duration"],
            data["steps"],
            data["repeat_count"],
            data["extra"],
            data.get("intensity", 1.0),
            data.get("priority", 0),
            data.get("category", "default")
        )


emotions = [
    Emotion("HAPPY", EFFECT_SLIDE, 600, 3500, 500, 40, 1, 0, 1.0, 1, "positive"),
    Emotion("SAD", EFFECT_SLIDE, 2800, 400, 700, 35, 1, 0, 0.8, 2, "negative"),
    Emotion("SURPRISED", EFFECT_TONE_SEQ, 800, 3000, 70, 0, 6, 0, 1.2, 3, "reactive"),
    Emotion("ANGRY", EFFECT_TONE_SEQ, 2500, 4000, 50, 0, 15, 0, 1.5, 5, "negative"),
    Emotion("IRRITATED", EFFECT_TONE_SEQ, 1500, 2500, 120, 0, 5, 80, 1.1, 4, "negative"),
    Emotion("PURR", EFFECT_CUSTOM, 180, 220, 2000, 3, 1, 5, 0.7, 1, "positive"),
    Emotion("PURR_DEEP", EFFECT_CUSTOM, 120, 180, 2500, 5, 1, 8, 0.8, 1, "positive"),
    Emotion("PURR_HIGH", EFFECT_CUSTOM, 220, 280, 1800, 4, 1, 10, 0.65, 1, "positive"),
    Emotion("CURIOUS", EFFECT_CUSTOM, 600, 2000, 400, 20, 1, 0, 1.0, 2, "reactive"),
    Emotion("CONFUSED", EFFECT_TONE_SEQ, 600, 2600, 100, 0, 8, 0, 0.9, 3, "reactive"),
    Emotion("EXCITED", EFFECT_CUSTOM, 800, 3500, 150, 8, 5, 0, 1.3, 4, "positive"),
    Emotion("TIRED", EFFECT_SLIDE, 1200, 300, 1000, 40, 1, 0, 0.6, 2, "neutral"),
    Emotion("TALK", EFFECT_CUSTOM, 0, 0, 0, 0, 1, 0, 1.0, 1, "neutral")
]

currentEmotion = -1
_VOL = 5000


def mute():
    pwm.duty_u16(0)


def play_tone(freq, duration_ms):
    if freq < 1:
        mute();
        time.sleep_ms(duration_ms);
        return
    pwm.freq(int(freq))
    pwm.duty_u16(_VOL)
    time.sleep_ms(duration_ms)
    mute()


def slide_tone(start_freq, end_freq, total_duration_ms, steps):
    if steps <= 0:
        play_tone(end_freq, total_duration_ms);
        return
    step_freq = (end_freq - start_freq) / steps
    step_dur = max(1, total_duration_ms // steps)
    f = start_freq
    for _ in range(steps):
        play_tone(f, step_dur)
        f += step_freq


def warble_tone(base_freq, total_duration_ms, depth):
    end_at = time.ticks_add(time.ticks_ms(), total_duration_ms)
    while time.ticks_diff(end_at, time.ticks_ms()) > 0:
        play_tone(base_freq + random.randint(-depth, depth), 35)



def play_chirp():
    for _ in range(random.randint(3, 6)):
        start = random.randint(500, 2500)
        end = random.randint(500, 2500)
        dur = random.randint(80, 250)
        steps = random.randint(8, 20)
        if random.getrandbits(1):
            slide_tone(start, end, dur, steps)
        else:
            warble_tone(start, dur, 120)
        time.sleep_ms(random.randint(20, 80))


def play_emotion(e):
    e.play()


def save_emotions_to_file(filename, emotion_list):
    try:
        with open(filename, 'w') as f:
            data = [e.to_dict() for e in emotion_list]
            f.write(str(data))
        return True
    except:
        return False


def load_emotions_from_file(filename):
    try:
        with open(filename, 'r') as f:
            data = eval(f.read())
            return [Emotion.from_dict(e) for e in data]
    except:
        return []


def create_mixed_emotion(name1, name2, weight=0.5, custom_name=None):
    """
    Helper function to create mixed emotions from existing ones based on their names.

    Args:
        name1: Name of the first emotion
        name2: Name of the second emotion
        weight: Weight of the second emotion (0.0 - 1.0)
        custom_name: Custom name for the new emotion (optional)

    Returns:
        A new emotion that is a mix of the two emotions or None if either doesn't exist
    """
    print(f"Creating mix: {name1} + {name2} (weight: {weight:.1f})")
    # Find emotions by names (case-insensitive)
    emotion1 = None
    emotion2 = None

    for e in emotions:
        if e.name == name1:
            emotion1 = e
        if e.name == name2:
            emotion2 = e

    if emotion1 and emotion2:
        result = emotion1.mix_with(emotion2, weight, custom_name)
        print(f"Mix created: {result.name}")
        return result

    if not emotion1:
        print(f"Error: Emotion '{name1}' not found")
    if not emotion2:
        print(f"Error: Emotion '{name2}' not found")
    return None

if __name__ == '__main__':

    poller = uselect.poll()
    poller.register(sys.stdin, uselect.POLLIN)


    def read_command_nonblocking():
        if poller.poll(0):
            return sys.stdin.readline().strip().upper()
        return None


    try:
        categories = sorted(list(set(e.category for e in emotions)))
        print("Commands: RANDOM, " + ", ".join([e.name for e in emotions]))
        print("Categories: " + ", ".join(categories))
        while True:
            cmd = read_command_nonblocking()
            if cmd is not None:
                print(f"Command received: {cmd}")

                # Handle MIX command separately before other commands
                if cmd.startswith("MIX "):
                    # Format: MIX EMOTION1 EMOTION2 WEIGHT CUSTOM_NAME
                    parts = cmd.split()
                    if len(parts) >= 3:
                        name1 = parts[1]
                        name2 = parts[2]
                        weight = 0.5  # default weight
                        custom_name = None

                        # Check if weight is specified
                        if len(parts) >= 4:
                            try:
                                weight = float(parts[3]) / 10.0  # scale 0-10 -> 0.0-1.0
                                weight = max(0.0, min(1.0, weight))  # limit range

                                # Check if name is specified after weight
                                if len(parts) >= 5:
                                    custom_name = parts[4]
                            except ValueError:
                                # If parts[3] is not a number, it's a name
                                custom_name = parts[3]

                        mixed = create_mixed_emotion(name1, name2, weight, custom_name)
                        if mixed:
                            # Save temporarily and use as current emotion
                            temp_emotion = mixed
                            currentEmotion = -2  # special value for temporary emotion
                            print(f"Created mixed emotion: {mixed.name} (weight: {weight:.1f})")
                        else:
                            print(f"Could not mix emotions {name1} and {name2}")
                elif cmd == "SAVE" and currentEmotion == -2 and temp_emotion:
                    # Save temporary emotion to the emotions list
                    emotions.append(temp_emotion)
                    currentEmotion = len(emotions) - 1
                    print(f"Saved mixed emotion as: {temp_emotion.name}")
                    print(f"Total emotions: {len(emotions)}")
                elif cmd == "RANDOM":
                    currentEmotion = -1
                    print("Mode set to: RANDOM")
                elif cmd in categories:
                    # Filter emotions by category and choose a random one
                    category_emotions = [i for i, e in enumerate(emotions) if e.category == cmd]
                    if category_emotions:
                        currentEmotion = random.choice(category_emotions)
                        print(f"Mode set to random {cmd} emotion: {emotions[currentEmotion].name}")
                else:
                    idx = next((i for i, e in enumerate(emotions) if e.name == cmd), None)
                    if idx is not None:
                        currentEmotion = idx
                        print(f"Mode set to: {emotions[currentEmotion].name}")
            emo_idx = currentEmotion if currentEmotion != -1 else random.randint(0, len(emotions) - 1)
            print(emotions[emo_idx].name)
            play_emotion(emotions[emo_idx])
            time.sleep_ms(random.randint(1000, 3000))
    except KeyboardInterrupt:
        pass
    finally:
        mute()
        pwm.deinit()
