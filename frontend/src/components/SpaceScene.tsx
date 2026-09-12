import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import earthMapUrl from "../assets/planets/earth_atmos_2048.jpg";
import earthSpecularUrl from "../assets/planets/earth_specular_2048.jpg";
import earthLightsUrl from "../assets/planets/earth_lights_2048.png";
import cloudsMapUrl from "../assets/planets/earth_clouds_1024.png";

/** 太阳方向（世界系，归一化）：决定地球昼夜分界与光源位置 */
const SUN_DIR = new THREE.Vector3(-4, 2.5, 9).normalize();

/**
 * 登录页 3D 太空场景（three.js）：
 * 地球用自定义昼夜着色器——日面真实贴图 + 海面镜面反光，夜面亮起城市灯光，
 * 晨昏线带一层暖色；云层独立球壳；远处是缓慢旋转的粒子银河。
 * 作为透明层叠在 2D 星空之上，失败时静默退回纯星空。
 */
export function SpaceScene({ className }: { className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || failed) return;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    } catch {
      setFailed(true);
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.setClearColor(0x000000, 0);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 300);
    camera.position.set(0, 0, 13.5);

    // --- 柔光圆点贴图（星星 / 银河粒子 / 太阳光晕共用） ---
    const glowTexture = (() => {
      const c = document.createElement("canvas");
      c.width = c.height = 128;
      const ctx = c.getContext("2d")!;
      const g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
      g.addColorStop(0, "rgba(255,255,255,1)");
      g.addColorStop(0.35, "rgba(255,255,255,0.5)");
      g.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, 128, 128);
      return new THREE.CanvasTexture(c);
    })();

    // --- 稀疏远景星幕（3D，随镜头产生视差；密集星空由底层 2D Starfield 负责） ---
    const stars = (() => {
      const COUNT = 900;
      const positions = new Float32Array(COUNT * 3);
      const colors = new Float32Array(COUNT * 3);
      const tint = [new THREE.Color("#ffffff"), new THREE.Color("#bcd0ff"), new THREE.Color("#ffe9c4")];
      for (let i = 0; i < COUNT; i++) {
        // 球壳分布，保证四面八方都有星
        const r = 55 + Math.random() * 50;
        const theta = Math.random() * Math.PI * 2;
        const phi = Math.acos(2 * Math.random() - 1);
        positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
        positions[i * 3 + 1] = r * Math.cos(phi);
        positions[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta);
        const c = tint[Math.floor(Math.random() * tint.length)];
        const b = 0.5 + Math.random() * 0.5;
        colors[i * 3] = c.r * b;
        colors[i * 3 + 1] = c.g * b;
        colors[i * 3 + 2] = c.b * b;
      }
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
      const mat = new THREE.PointsMaterial({
        size: 0.28,
        sizeAttenuation: true,
        map: glowTexture,
        vertexColors: true,
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      });
      return new THREE.Points(geo, mat);
    })();
    scene.add(stars);

    // --- 银河：三条旋臂的粒子盘 + 发光核心 ---
    const galaxy = (() => {
      const COUNT = 7000;
      const RADIUS = 14;
      const IN = new THREE.Color("#ffd9a6");
      const MID = new THREE.Color("#9db4ff");
      const OUT = new THREE.Color("#b07fe8");
      const positions = new Float32Array(COUNT * 3);
      const colors = new Float32Array(COUNT * 3);
      const rnd = (f: number) => Math.pow(Math.random(), 2.2) * (Math.random() < 0.5 ? 1 : -1) * f;
      for (let i = 0; i < COUNT; i++) {
        const t = Math.pow(Math.random(), 1.8);
        const r = t * RADIUS;
        let x: number;
        let y: number;
        let z: number;
        let c: THREE.Color;
        if (i % 7 === 0) {
          // 核心球状隆起：暖白色高密度
          x = rnd(1.6);
          y = rnd(1.0);
          z = rnd(1.6);
          c = IN.clone();
        } else {
          const branch = ((i % 3) / 3) * Math.PI * 2 + r * 0.09;
          const spread = 0.14 * r + 0.4;
          x = Math.cos(branch) * r + rnd(spread);
          y = rnd(spread * 0.35);
          z = Math.sin(branch) * r + rnd(spread);
          c = IN.clone()
            .lerp(MID, Math.min(1, t * 1.5))
            .lerp(OUT, Math.max(0, t - 0.45) / 0.55);
        }
        const b = 0.5 + Math.random() * 0.5;
        positions[i * 3] = x;
        positions[i * 3 + 1] = y;
        positions[i * 3 + 2] = z;
        colors[i * 3] = c.r * b;
        colors[i * 3 + 1] = c.g * b;
        colors[i * 3 + 2] = c.b * b;
      }
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
      const mat = new THREE.PointsMaterial({
        size: 0.24,
        sizeAttenuation: true,
        map: glowTexture,
        vertexColors: true,
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      });
      const points = new THREE.Points(geo, mat);
      // 银心光晕
      const core = new THREE.Sprite(
        new THREE.SpriteMaterial({
          map: glowTexture,
          color: 0xffe3b8,
          transparent: true,
          opacity: 0.4,
          depthWrite: false,
          blending: THREE.AdditiveBlending,
        }),
      );
      core.scale.setScalar(5);
      points.add(core);
      return points;
    })();
    scene.add(galaxy);

    // --- 地球组：昼夜着色器本体 + 云层 + 大气辉光 + 月球 ---
    const earthGroup = new THREE.Group();
    const tiltGroup = new THREE.Group();
    tiltGroup.rotation.z = THREE.MathUtils.degToRad(23.4); // 黄赤交角
    earthGroup.add(tiltGroup);

    // 1x1 占位贴图：贴图加载完成前渲染第一帧不报错
    const placeholder = (r: number, g: number, b: number) => {
      const t = new THREE.DataTexture(new Uint8Array([r, g, b, 255]), 1, 1);
      t.needsUpdate = true;
      return t;
    };
    const earthUniforms: Record<string, THREE.IUniform> = {
      dayMap: { value: placeholder(8, 14, 32) },
      nightMap: { value: placeholder(0, 0, 0) },
      specMap: { value: placeholder(0, 0, 0) },
      sunDir: { value: SUN_DIR },
    };
    const earthMat = new THREE.ShaderMaterial({
      uniforms: earthUniforms,
      vertexShader: `
        varying vec2 vUv;
        varying vec3 vNormalW;
        varying vec3 vPosW;
        void main() {
          vUv = uv;
          vNormalW = normalize(mat3(modelMatrix) * normal);
          vec4 wp = modelMatrix * vec4(position, 1.0);
          vPosW = wp.xyz;
          gl_Position = projectionMatrix * viewMatrix * wp;
        }
      `,
      fragmentShader: `
        uniform sampler2D dayMap;
        uniform sampler2D nightMap;
        uniform sampler2D specMap;
        uniform vec3 sunDir;
        varying vec2 vUv;
        varying vec3 vNormalW;
        varying vec3 vPosW;
        void main() {
          vec3 N = normalize(vNormalW);
          vec3 V = normalize(cameraPosition - vPosW);
          float sunDot = dot(N, sunDir);
          float dayMix = smoothstep(-0.15, 0.25, sunDot);

          // 日面：贴图 + 漫反射塑形
          vec3 dayCol = texture2D(dayMap, vUv).rgb;
          vec3 dayLit = dayCol * (0.35 + 0.9 * max(sunDot, 0.0));

          // 夜面：城市灯光（暖色）+ 一点点月照蓝，避免死黑
          vec3 nightCol = texture2D(nightMap, vUv).rgb;
          vec3 nightLit = nightCol * vec3(1.0, 0.85, 0.6) * 2.0;
          nightLit += dayCol * vec3(0.04, 0.05, 0.09);

          vec3 color = mix(nightLit, dayLit, dayMix);

          // 海面镜面反光（太阳耀斑，高光收紧成一小片）
          float specMask = texture2D(specMap, vUv).r;
          vec3 H = normalize(sunDir + V);
          float spec = pow(max(dot(N, H), 0.0), 64.0) * specMask * dayMix;
          color += spec * vec3(1.0, 0.85, 0.6) * 0.42;

          // 晨昏线暖色（日出日落带）
          float twilight = exp(-pow(sunDot / 0.13, 2.0));
          color += twilight * vec3(0.95, 0.4, 0.12) * 0.22;

          // 边缘大气蓝（日面一侧更亮）
          float fres = pow(1.0 - max(dot(N, V), 0.0), 2.6);
          color += fres * vec3(0.25, 0.5, 1.0) * (0.3 + 0.45 * dayMix);

          gl_FragColor = vec4(color, 1.0);
          #include <colorspace_fragment>
        }
      `,
    });
    const earth = new THREE.Mesh(new THREE.SphereGeometry(1, 96, 64), earthMat);
    tiltGroup.add(earth);

    const cloudsMat = new THREE.MeshLambertMaterial({ transparent: true, opacity: 0.8, depthWrite: false });
    const clouds = new THREE.Mesh(new THREE.SphereGeometry(1.015, 96, 64), cloudsMat);
    tiltGroup.add(clouds);

    // 大气辉光：背面菲涅尔壳
    const atmosphere = new THREE.Mesh(
      new THREE.SphereGeometry(1, 64, 48),
      new THREE.ShaderMaterial({
        vertexShader: `
          varying vec3 vN;
          void main() {
            vN = normalize(normalMatrix * normal);
            gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
          }
        `,
        fragmentShader: `
          varying vec3 vN;
          void main() {
            float i = pow(0.68 - dot(vN, vec3(0.0, 0.0, 1.0)), 3.0) * 0.65;
            gl_FragColor = vec4(0.3, 0.55, 1.0, 1.0) * i;
          }
        `,
        blending: THREE.AdditiveBlending,
        side: THREE.BackSide,
        transparent: true,
        depthWrite: false,
      }),
    );
    atmosphere.scale.setScalar(1.18);
    earthGroup.add(atmosphere);
    scene.add(earthGroup);

    // --- 太阳光晕（画面左上方向，光源同侧） ---
    const sun = new THREE.Sprite(
      new THREE.SpriteMaterial({
        map: glowTexture,
        color: 0xfff1d8,
        transparent: true,
        opacity: 0.55,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      }),
    );
    sun.scale.setScalar(10);
    scene.add(sun);

    // --- 光照（云层/月球用内置光照，地球走自定义着色器） ---
    const sunLight = new THREE.DirectionalLight(0xfff1dd, 2.0);
    sunLight.position.copy(SUN_DIR).multiplyScalar(10);
    scene.add(sunLight);
    scene.add(new THREE.AmbientLight(0x445577, 0.7));
    const fill = new THREE.DirectionalLight(0x8899ff, 0.3);
    fill.position.set(6, -2, 8);
    scene.add(fill);

    // --- 尺寸与布局（横屏地球偏左下，竖屏居中偏下，避开登录卡片） ---
    let w = 1;
    let h = 1;
    const applyLayout = () => {
      const aspect = w / h;
      if (aspect >= 1) {
        earthGroup.position.set(-3.6, -2.7, 0);
        earthGroup.scale.setScalar(3.2);
        galaxy.position.set(4.5, 2.6, -75);
        galaxy.scale.setScalar(1.25);
        galaxy.rotation.set(-1.05, 0, 0.35);
        sun.position.set(-14, 7.5, -9);
      } else {
        earthGroup.position.set(0.2, -5.2, 0);
        earthGroup.scale.setScalar(3.3);
        galaxy.position.set(0.5, 4.2, -80);
        galaxy.scale.setScalar(1.1);
        galaxy.rotation.set(-1.15, 0, 0.2);
        sun.position.set(-11, 8.5, -11);
      }
    };
    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      w = Math.max(1, rect.width);
      h = Math.max(1, rect.height);
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      applyLayout();
      if (reducedMotion) renderFrame(0);
    };
    window.addEventListener("resize", resize);

    // --- 镜头视差（指针 + 无操作时的缓慢漂移） ---
    let px = 0;
    let py = 0;
    const onPointerMove = (e: PointerEvent) => {
      px = e.clientX / w - 0.5;
      py = e.clientY / h - 0.5;
    };
    window.addEventListener("pointermove", onPointerMove, { passive: true });

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf = 0;
    const clock = new THREE.Clock();

    const renderFrame = (dt: number) => {
      const t = clock.elapsedTime;
      earth.rotation.y += dt * 0.032;
      clouds.rotation.y += dt * 0.041;
      stars.rotation.y += dt * 0.004;
      galaxy.rotation.z += dt * 0.02;

      const idleX = Math.sin(t * 0.07) * 0.18;
      const idleY = Math.cos(t * 0.05) * 0.1;
      const ease = Math.min(1, dt * 2.5);
      camera.position.x += (idleX + px * 0.9 - camera.position.x) * ease;
      camera.position.y += (idleY - py * 0.6 - camera.position.y) * ease;
      camera.lookAt(0, -0.6, 0);
      renderer.render(scene, camera);
    };

    const tick = () => {
      const dt = Math.min(0.05, clock.getDelta());
      renderFrame(dt);
      raf = requestAnimationFrame(tick);
    };

    let cancelled = false;
    const loadTexture = (url: string, srgb: boolean) =>
      new THREE.TextureLoader().loadAsync(url).then((t) => {
        if (srgb) t.colorSpace = THREE.SRGBColorSpace;
        t.anisotropy = renderer.capabilities.getMaxAnisotropy();
        return t;
      }).catch(() => null);

    Promise.all([
      loadTexture(earthMapUrl, true),
      loadTexture(earthSpecularUrl, false),
      loadTexture(earthLightsUrl, false),
      loadTexture(cloudsMapUrl, true),
    ]).then(([earthMap, specMap, lightsMap, cloudsMap]) => {
      if (cancelled) return;
      if (earthMap) earthUniforms.dayMap.value = earthMap;
      if (specMap) earthUniforms.specMap.value = specMap;
      if (lightsMap) earthUniforms.nightMap.value = lightsMap;
      if (cloudsMap) {
        cloudsMat.map = cloudsMap;
        cloudsMat.needsUpdate = true;
      }
      resize();
      if (reducedMotion) {
        renderFrame(0);
      } else {
        raf = requestAnimationFrame(tick);
      }
      setReady(true);
    });

    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointermove", onPointerMove);
      scene.traverse((obj) => {
        const mesh = obj as THREE.Mesh & { material?: THREE.Material | THREE.Material[] };
        mesh.geometry?.dispose?.();
        const m = mesh.material;
        if (Array.isArray(m)) m.forEach((x) => x.dispose());
        else m?.dispose();
      });
      glowTexture.dispose();
      renderer.dispose();
    };
    // failed 状态只用于触发回退，不需要重跑场景
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [failed]);

  if (failed) return null;
  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className={`${className ?? ""} opacity-0 transition-opacity duration-1000 ${ready ? "opacity-100" : ""}`}
    />
  );
}
