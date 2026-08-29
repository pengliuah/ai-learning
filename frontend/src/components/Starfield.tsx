import { useEffect, useRef } from "react";

interface Star {
  x: number;
  y: number;
  r: number;
  baseAlpha: number;
  twinkleSpeed: number;
  phase: number;
  drift: number;
  color: string;
}

interface Meteor {
  x: number;
  y: number;
  vx: number;
  vy: number;
  life: number;
  maxLife: number;
}

const STAR_COLORS = ["#ffffff", "#ffffff", "#ffffff", "#bcd0ff", "#ffe9c4"];

function spawnStar(w: number, h: number): Star {
  return {
    x: Math.random() * w,
    y: Math.random() * h,
    r: 0.4 + Math.random() * 1.3,
    baseAlpha: 0.35 + Math.random() * 0.6,
    twinkleSpeed: 0.5 + Math.random() * 1.8,
    phase: Math.random() * Math.PI * 2,
    drift: 1.5 + Math.random() * 4,
    color: STAR_COLORS[Math.floor(Math.random() * STAR_COLORS.length)],
  };
}

/**
 * 探索星空：全屏闪烁星空 + 偶尔划过的流星（纯 canvas，无依赖）。
 * 页面任意点击会从点击处划出一颗流星（点哪划哪）。
 * 用法：<Starfield className="absolute inset-0 h-full w-full" />
 */
export function Starfield({ className }: { className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let raf = 0;
    let w = 0;
    let h = 0;
    let stars: Star[] = [];
    let meteors: Meteor[] = [];
    const dpr = Math.min(window.devicePixelRatio || 1, 2);

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      w = rect.width;
      h = rect.height;
      canvas.width = Math.max(1, Math.floor(w * dpr));
      canvas.height = Math.max(1, Math.floor(h * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const count = Math.min(260, Math.floor((w * h) / 4200));
      stars = Array.from({ length: count }, () => spawnStar(w, h));
    };

    /** 随机生成一颗环境流星；传入坐标则从该点出发（点击交互）。 */
    const spawnMeteor = (x?: number, y?: number) => {
      const speed = 420 + Math.random() * 260;
      if (x !== undefined && y !== undefined) {
        // 点击流星：从点击点向斜下方划过，方向随机左右，更快更亮
        const fromLeft = Math.random() < 0.5;
        const angle = (fromLeft ? 0.3 : Math.PI - 0.3) + (Math.random() - 0.5) * 0.25;
        meteors.push({
          x, y,
          vx: Math.cos(angle) * (speed + 200),
          vy: Math.abs(Math.sin(angle)) * (speed + 200),
          life: 0,
          maxLife: 1 + Math.random() * 0.4,
        });
        return;
      }
      const fromLeft = Math.random() < 0.5;
      const angle = (fromLeft ? 0.35 : Math.PI - 0.35) + (Math.random() - 0.5) * 0.2;
      meteors.push({
        x: fromLeft ? -20 : w + 20,
        y: Math.random() * h * 0.4,
        vx: Math.cos(angle) * speed,
        vy: Math.abs(Math.sin(angle)) * speed,
        life: 0,
        maxLife: 0.9 + Math.random() * 0.7,
      });
    };

    const onPointerDown = (e: PointerEvent) => {
      spawnMeteor(e.clientX, e.clientY);
    };

    let last = performance.now();
    const tick = (now: number) => {
      const dt = Math.min(50, now - last) / 1000;
      last = now;
      ctx.clearRect(0, 0, w, h);

      // 星星：缓慢向左漂移 + 各自相位闪烁
      for (const s of stars) {
        s.phase += s.twinkleSpeed * dt;
        s.x -= s.drift * dt;
        if (s.x < -3) {
          s.x = w + 3;
          s.y = Math.random() * h;
        }
        const a = s.baseAlpha * (0.55 + 0.45 * Math.sin(s.phase));
        ctx.globalAlpha = Math.max(0.04, a);
        ctx.fillStyle = s.color;
        ctx.beginPath();
        ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
        ctx.fill();
      }

      // 流星：环境流星低概率生成（最多两颗）；点击流星不受限
      if (Math.random() < dt * 0.22 && meteors.length < 2) spawnMeteor();
      meteors = meteors.filter((m) => m.life < m.maxLife && m.x > -80 && m.x < w + 80 && m.y < h + 80);
      for (const m of meteors) {
        m.life += dt;
        m.x += m.vx * dt;
        m.y += m.vy * dt;
        const fade = 1 - m.life / m.maxLife;
        const tail = 16;
        const grad = ctx.createLinearGradient(
          m.x, m.y,
          m.x - m.vx * 0.001 * tail * 60, m.y - m.vy * 0.001 * tail * 60,
        );
        grad.addColorStop(0, `rgba(255,255,255,${0.9 * fade})`);
        grad.addColorStop(1, "rgba(255,255,255,0)");
        ctx.globalAlpha = 1;
        ctx.strokeStyle = grad;
        ctx.lineWidth = 1.6;
        ctx.lineCap = "round";
        ctx.beginPath();
        ctx.moveTo(m.x, m.y);
        ctx.lineTo(m.x - m.vx * 0.095, m.y - m.vy * 0.095);
        ctx.stroke();
      }

      ctx.globalAlpha = 1;
      raf = requestAnimationFrame(tick);
    };

    resize();
    window.addEventListener("resize", resize);
    window.addEventListener("pointerdown", onPointerDown);
    raf = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointerdown", onPointerDown);
    };
  }, []);

  return <canvas ref={canvasRef} className={className} aria-hidden="true" />;
}
