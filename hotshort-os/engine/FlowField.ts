import graphLayout from "./GraphLayout";

export interface FlowPoint {
  x: number;
  y: number;
}

class FlowField {
  getPoint(
    from: string,
    to: string,
    progress: number
  ): FlowPoint {
    const bezier = graphLayout.getBezier(from, to);

    if (!bezier) {
      return {
        x: 0,
        y: 0,
      };
    }

    const t = this.ease(progress);

    const { start, c1, c2, end } = bezier;

    return {
      x: this.cubic(
        start.x,
        c1.x,
        c2.x,
        end.x,
        t
      ),

      y: this.cubic(
        start.y,
        c1.y,
        c2.y,
        end.y,
        t
      ),
    };
  }

  getDirection(
    from: string,
    to: string,
    progress: number
  ) {
    const p1 = this.getPoint(
      from,
      to,
      progress
    );

    const p2 = this.getPoint(
      from,
      to,
      Math.min(progress + 0.01, 1)
    );

    const angle =
      Math.atan2(
        p2.y - p1.y,
        p2.x - p1.x
      ) *
      (180 / Math.PI);

    return angle;
  }

  getVelocity(progress: number) {
    return (
      0.35 +
      Math.sin(progress * Math.PI) * 0.65
    );
  }

  private cubic(
    p0: number,
    p1: number,
    p2: number,
    p3: number,
    t: number
  ) {
    const mt = 1 - t;

    return (
      mt * mt * mt * p0 +
      3 * mt * mt * t * p1 +
      3 * mt * t * t * p2 +
      t * t * t * p3
    );
  }

  private ease(t: number) {
    return t < .5
      ? 4 * t * t * t
      : 1 -
          Math.pow(
            -2 * t + 2,
            3
          ) /
            2;
  }
}

const flowField = new FlowField();

export default flowField;