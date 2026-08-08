`timescale 1ns/1ps
module tb_fsm;
    reg clk = 0;
    reg rst_n = 0;
    reg start = 0;
    wire busy, done;

    fsm dut (.clk(clk), .rst_n(rst_n), .start(start), .busy(busy), .done(done));

    always #5 clk = ~clk;

    integer errors = 0;

    task check(input cond, input [255:0] msg, input integer cycle);
        begin
            if (!cond) begin
                $display("RTLVERDICT_RESULT: FAIL at cycle %0d: %0s", cycle, msg);
                errors = errors + 1;
                $finish;
            end
        end
    endtask

    integer i;
    initial begin
        repeat (2) @(posedge clk);
        @(negedge clk);
        rst_n = 1;

        // after reset: not busy, not done
        @(negedge clk);
        check(busy == 0 && done == 0, "not idle after reset", 0);

        // start a transaction, expect busy within 1 cycle
        start = 1;
        @(negedge clk);
        start = 0;
        check(busy == 1, "busy not asserted after start", 1);

        // run for up to 10 cycles waiting for done
        for (i = 0; i < 10; i = i + 1) begin
            @(negedge clk);
            if (done) begin
                i = 100; // break
            end
        end
        check(done == 1 || busy == 0, "never completed transaction", 10);

        @(negedge clk);
        check(busy == 0, "busy still asserted after done", 11);

        $display("RTLVERDICT_RESULT: PASS");
        $finish;
    end

    initial begin
        #2000;
        $display("RTLVERDICT_RESULT: FAIL at cycle unknown: timeout, testbench did not finish");
        $finish;
    end
endmodule
