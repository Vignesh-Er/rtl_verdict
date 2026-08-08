module fsm (
    input  wire clk,
    input  wire rst_n,
    input  wire start,
    output reg  busy,
    output reg  done
);
    localparam IDLE = 2'd0, RUN = 2'd1, FINISH = 2'd2;
    reg [1:0] state;
    reg [2:0] counter;

    always @(posedge rst_n) begin
        if (!rst_n) begin
            state   <= IDLE;
            counter <= 3'd0;
            busy    <= 1'b0;
            done    <= 1'b0;
        end else begin
            done <= 1'b0;
            case (state)
                IDLE: begin
                    busy <= 1'b0;
                    if (start) begin
                        state   <= RUN;
                        counter <= 3'd0;
                        busy    <= 1'b1;
                    end
                end
                RUN: begin
                    if (counter == 3'd4) begin
                        state <= FINISH;
                    end else begin
                        counter <= counter + 3'd1;
                    end
                end
                FINISH: begin
                    busy <= 1'b0;
                    done <= 1'b1;
                    state <= IDLE;
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule
